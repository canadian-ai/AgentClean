const BASE = "https://api.github.com";
const signatures = {
  claude: [
    /^\s*co-authored-by:\s*claude(?:\s+code)?\b.*$/i,
    /^\s*🤖\s*generated with \[?claude code\]?.*$/i,
    /^\s*claude-session:\s*.*$/i
  ],
  codex: [
    /^\s*co-authored-by:\s*(?:openai\s+)?codex\b.*$/i,
    /^\s*(?:generated|assisted) (?:with|by) (?:openai\s+)?codex\b.*$/i
  ],
  cursor: [
    /^\s*co-authored-by:\s*cursor\b.*$/i,
    /^\s*(?:generated|assisted) (?:with|by) cursor\b.*$/i
  ],
  codesmith: [/^\s*co-authored-by:\s*codesmith\b.*$/i],
  opencode: [/^\s*co-authored-by:\s*opencode(?:-agent)?(?:\[bot\])?(?=\s|$).*$/i],
  gemini: [
    /^\s*co-authored-by:\s*(?:google\s+)?gemini\b.*$/i,
    /^\s*(?:generated|assisted) (?:with|by) gemini(?: cli)?\b.*$/i
  ]
};
function clean(message, agents) {
  const removed = {};
  const lines = message.split("\n").filter(line => {
    for (const agent of agents) {
      if (signatures[agent]?.some(re => re.test(line))) {
        removed[agent] = (removed[agent] || 0) + 1;
        return false;
      }
    }
    return true;
  });
  const result = lines.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd();
  return {message: result, removed};
}
function fail(message, status = 400) {
  const err = new Error(message);
  err.status = status;
  throw err;
}
function validate(body) {
  const owner = body.owner, repo = body.repo, branch = body.branch || "main";
  if (![owner,repo,branch].every(x => typeof x === "string" && x.length < 200)) fail("Invalid repository or branch");
  if (!/^[A-Za-z0-9_.-]+$/.test(owner) || !/^[A-Za-z0-9_.-]+$/.test(repo) || !/^[A-Za-z0-9_./-]+$/.test(branch) || branch.includes("..") || branch.startsWith("/") || branch.endsWith("/")) fail("Invalid GitHub repository reference");
  return {owner,repo,branch};
}
async function github(path, token, options = {}) {
  const r = await fetch(BASE + path, {
    method: options.method || "GET",
    headers: {
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(token ? {"Authorization": "Bearer " + token} : {}),
      ...(options.body ? {"Content-Type": "application/json"} : {})
    },
    ...(options.body ? {body: JSON.stringify(options.body)} : {}),
    cache: "no-store"
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) fail(data.message || "GitHub request failed", r.status);
  return data;
}
// Classifications are advisory; preserve actual Git authorship. Automation
// identities can be preapproved for filtering without rewriting their commits.
function contributorCategory(name = "", email = "") {
  const identity = name + " " + email;
  if (/(?:claude|codex|codesmith|cursor|gemini|opencode(?:-agent)?)/i.test(identity)) return "ai-agent";
  if (/(?:\\[bot\\]|github-actions|dependabot|renovate)/i.test(identity)) return "automation";
  return "human";
}
function contributorCheck(commits, partial) {
  const authors = new Map();
  const committers = new Map();
  for (const item of commits) {
    for (const [records, data] of [[authors, item.commit.author], [committers, item.commit.committer]]) {
      const name = data?.name || "Unknown", email = data?.email || "";
      const key = JSON.stringify([name, email]);
      if (!records.has(key)) records.set(key, { name, email, category: contributorCategory(name, email), commits: 0 });
      records.get(key).commits++;
    }
  }
  const sorted = map => [...map.values()].sort((a,b) => b.commits-a.commits);
  const authorRows = sorted(authors), committerRows = sorted(committers);
  return {
    authors: authorRows, committers: committerRows, partial,
    autoApproved: authorRows.filter(a => a.category !== "human"),
    humanCount: authorRows.filter(a => a.category === "human").length,
    hasAutomatedAuthors: authorRows.some(a => a.category !== "human"),
  };
}
async function scan(body, token) {
  const {owner,repo,branch} = validate(body);
  const prefix = "/repos/" + encodeURIComponent(owner) + "/" + encodeURIComponent(repo);
  const branchInfo = await github(prefix + "/branches/" + branch.split("/").map(encodeURIComponent).join("/"), token);
  const head = branchInfo.commit.sha;
  const commits = await github(prefix + "/commits?sha=" + encodeURIComponent(branch) + "&per_page=101", token);
  // GitHub caps per_page at 100. A second-page check prevents incomplete rewrites.
  const older = commits.length === 100 ? await github(prefix + "/commits?sha=" + encodeURIComponent(branch) + "&per_page=1&page=101", token) : [];
  const tooLarge = commits.length === 100 && older.length > 0;
  const agents = Object.keys(signatures);
  const rows = commits.map(c => {
    const matches = clean(c.commit.message, agents);
    return {
      sha: c.sha,
      message: c.commit.message,
      nextMessage: matches.message,
      removed: matches.removed,
      parents: c.parents.length,
      author: c.commit.author?.name || "Unknown",
      date: c.commit.author?.date || null,
      signed: c.commit.verification?.verified || false
    };
  });
  return {repo:owner+"/"+repo,branch,head,protected:branchInfo.protected,tooLarge,commits:rows,available:rows.filter(r=>Object.keys(r.removed).length).length, scanned:rows.length,contributorCheck:contributorCheck(commits,tooLarge)};
}
async function apply(body, token) {
  if (!token) fail("A GitHub fine-grained token is required for cleanup", 401);
  const {owner,repo,branch} = validate(body);
  const agents = Array.isArray(body.agents) ? body.agents.filter(a=>Object.prototype.hasOwnProperty.call(signatures,a)) : [];
  if (!agents.length) fail("Select at least one agent");
  if (body.confirm !== "REWRITE HISTORY") fail("Explicit confirmation required");
  const prefix = "/repos/"+encodeURIComponent(owner)+"/"+encodeURIComponent(repo);
  const result = await scan(body, token);
  if (result.head !== body.head) fail("Branch changed since preview. Scan again.",409);
  if (result.tooLarge || result.scanned >= 100) fail("This branch exceeds the 99-commit safety limit", 422);
  if (result.protected) fail("Protected branches cannot be rewritten by AgentClean",403);
  if (result.commits.some(c=>c.parents>1)) fail("Merge commits are not supported. No changes made.",422);
  if (result.commits.some(c=>c.signed)) fail("Signed commits are not supported. No changes made.",422);
  const eligible = result.commits.filter(c=>clean(c.message,agents).message!==c.message);
  if (!eligible.length) return {changed:0, head:result.head, backup:null};
  // If a non-root history is present, preserve the untouched ancestor.
  const oldest = result.commits[result.commits.length-1];
  const oldestFull = await github(prefix+"/git/commits/"+oldest.sha, token);
  let parent = oldestFull.parents[0]?.sha || null;
  const backup = "agentclean-backup-"+Date.now();
  await github(prefix+"/git/refs",token,{method:"POST",body:{ref:"refs/heads/"+backup,sha:result.head}});
  let created = 0;
  for (const row of [...result.commits].reverse()) {
    const original = await github(prefix+"/git/commits/"+row.sha, token);
    const updated = clean(original.message,agents).message;
    if (updated === original.message && parent === original.parents[0]?.sha) {
      parent = row.sha;
      continue;
    }
    const bodyCommit = {
      message:updated,
      tree:original.tree.sha,
      parents:parent?[parent]:[],
      author:original.author,
      committer:original.committer
    };
    const next = await github(prefix+"/git/commits",token,{method:"POST",body:bodyCommit});
    parent=next.sha;
    created++;
  }
  // Optimistic concurrency: force=false will fail rather than clobber new commits.
  // Rewriting a branch is non-fast-forward, so re-check the head before the forced update.
  const now=await github(prefix+"/git/ref/heads/"+branch.split("/").map(encodeURIComponent).join("/"),token);
  if(now.object.sha !== result.head) fail("Branch moved. Backup exists at "+backup+"; no branch update performed.",409);
  await github(prefix+"/git/refs/heads/"+branch.split("/").map(encodeURIComponent).join("/"),token,{method:"PATCH",body:{sha:parent,force:true}});
  return {changed:eligible.length,rebuilt:created,head:parent,backup,oldHead:result.head};
}
module.exports = async function handler(req,res) {
  res.setHeader("Cache-Control","no-store");
  if(req.method!=="POST") return res.status(405).json({error:"Method not allowed"});
  try {
    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body || {};
    const token = typeof req.headers["x-github-token"] === "string" ? req.headers["x-github-token"].trim() : "";
    if(token.length>500) fail("Invalid token");
    const result = body.action === "apply" ? await apply(body,token) : await scan(body,token);
    return res.status(200).json(result);
  } catch (err) {
    return res.status(err.status >= 400 && err.status < 600 ? err.status : 500).json({error:err.message || "Unexpected error"});
  }
};