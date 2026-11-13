const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('api/repository.js', 'utf8');
const context = { module: { exports: {} } };
vm.runInNewContext(source + '\nmodule.exports.auditTest = {contributorCategory, contributorCheck};', context);
const { contributorCategory, contributorCheck } = context.module.exports.auditTest;

test('agent and GitHub Actions identities are auto-classified', () => {
  assert.equal(contributorCategory('Claude', 'noreply@anthropic.com'), 'ai-agent');
  assert.equal(contributorCategory('github-actions[bot]', 'github-actions[bot]@users.noreply.github.com'), 'automation');
  assert.equal(contributorCategory('Ola', 'olaolukiyesi@gmail.com'), 'human');
  assert.equal(contributorCategory('tyrellshawn', 'tyrellshawn@users.noreply.github.com'), 'human');
});
test('reports bot-authored commits without reassigning attribution', () => {
  const commits = [
    {commit:{author:{name:'Claude', email:'noreply@anthropic.com'},committer:{name:'Ola',email:'ola@example.test'}}},
    {commit:{author:{name:'Ola',email:'ola@example.test'},committer:{name:'github-actions[bot]',email:'bot@example.test'}}},
  ];
  const report = contributorCheck(commits,true);
  assert.equal(report.humanCount,1);
  assert.equal(report.autoApproved.length,1);
  assert.equal(report.autoApproved[0].name,'Claude');
  assert.equal(report.partial,true);
  assert.equal(report.committers.some(x => x.name === 'github-actions[bot]' && x.category==='automation'),true);
});
