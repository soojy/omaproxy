const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const model = {};
vm.createContext(model);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../LimitModel.js'), 'utf8'), model);

const windows = [{label: 'Weekly'}, {label: 'Spark · 5-hour'}, {label: 'Spark · Weekly'}];
assert.equal(model.visibleWindows(windows, false).length, 1);
assert.equal(model.visibleWindows(windows, false)[0].label, 'Weekly');
assert.equal(model.visibleWindows(windows, true).length, 3);
assert.equal(model.primaryWindows([{label: 'Monthly'}])[0].label, 'Monthly');
assert.equal(model.primaryWindows([{label: '5-hour'}]).length, 0);
assert.equal(model.primaryWindows([{label: 'Claude · weekly'}]).length, 1);
assert.equal(model.planLabel('codex', 'pro'), 'PRO · 20×');
for (const name of ['prolite', 'pro_lite', 'pro-lite', 'pro_5x']) {
    assert.equal(model.planLabel('codex', name), 'PRO · 5×');
}
assert.equal(model.planLabel('codex', 'plus'), 'PLUS');
assert.equal(model.planLabel('codex', 'future_plan'), 'FUTURE PLAN');
assert.equal(model.planLabel('claude', 'pro'), 'PRO');
assert.equal(model.planLabel('codex', ''), '');
assert.equal(model.maskEmails('person@example.com', true), '[email hidden]');
assert.equal(model.maskEmails('codex-person@example.com-pro.json', true), '[email hidden]');
assert.equal(model.maskEmails('Loaded person@example.com and second@example.org', true), 'Loaded [email hidden] and [email hidden]');
assert.equal(model.maskEmails('person@example.com', false), 'person@example.com');
assert.equal(model.maskEmails('No email', true), 'No email');
console.log('Limit filtering and provider-specific plan labels passed.');
