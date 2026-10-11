const assert = require('node:assert/strict');
const {buildAuthReturnUrl} = require('../../web-source/js/auth-recovery.js');
assert.equal(typeof buildAuthReturnUrl, 'function', 'auth return helper must be available');
const base='https://example.com/app/profile.html';
const destination='report.html?key=大阪%3A%3A北区';
assert.equal(new URL(buildAuthReturnUrl(`${base}?return_to=${encodeURIComponent(destination)}`)).searchParams.get('key'),'大阪::北区');
for(const target of ['https://evil.test/report.html','//evil.test/report.html','javascript:alert(1)','admin.html','../report.html','https://user:password@example.com/app/report.html','profile.html?return_to=profile.html']){
 assert.equal(buildAuthReturnUrl(`${base}?return_to=${encodeURIComponent(target)}`),'',target);
}
assert.equal(buildAuthReturnUrl(`${base}?return=${encodeURIComponent('projects.html')}`),'https://example.com/app/projects.html');
console.log('auth return checks passed');
