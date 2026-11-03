const API = "https://api.github.com";
async function request(path, token) {
  const response = await fetch(API + path, {
    headers: {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      Authorization: "Bearer " + token
    },
    cache: "no-store"
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(response.status === 401 ? "Invalid or expired GitHub token." : data.message || "GitHub request failed.");
    error.status = response.status;
    throw error;
  }
  return data;
}
module.exports = async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store, private");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.method !== "POST") return res.status(405).json({error:"Method not allowed"});
  try {
    const token = req.headers["x-github-token"];
    if (typeof token !== "string" || !token.trim() || token.length > 500 || /[\r\n]/.test(token)) {
      return res.status(401).json({error:"Provide your GitHub personal access token."});
    }
    const user = await request("/user", token.trim());
    const repos = [];
    // Fine-grained tokens only expose repositories selected during authorization.
    // Load up to 300 repos; avoid an unbounded API request in a serverless function.
    for (let page = 1; page <= 3; page++) {
      const batch = await request("/user/repos?affiliation=owner,collaborator,organization_member&sort=updated&per_page=100&page=" + page, token.trim());
      repos.push(...batch.map(r => ({
        id: r.id,
        full_name: r.full_name,
        owner: r.owner.login,
        name: r.name,
        private: r.private,
        default_branch: r.default_branch,
        can_push: Boolean(r.permissions?.push || r.permissions?.admin || r.permissions?.maintain)
      })));
      if (batch.length < 100) break;
    }
    return res.status(200).json({user:{login:user.login,avatar_url:user.avatar_url},repositories:repos});
  } catch (err) {
    return res.status(err.status >= 400 && err.status < 600 ? err.status : 500).json({error:err.message || "Unable to list repositories."});
  }
};