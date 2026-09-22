const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../app.js'), 'utf8');
const start = source.indexOf('function applyProductSelection');
const end = source.indexOf('\n}\n\nfunction pruneSelectedProducts', start) + 2;
assert.ok(start >= 0 && end > start, 'selection helper not found');

const sandbox = {};
vm.runInNewContext(source.slice(start, end), sandbox);
const selected = new Set([99]);
const filteredAcrossPages = [{id: 1}, {id: 2}, {id: 3}];

sandbox.applyProductSelection(selected, filteredAcrossPages, true);
assert.deepEqual([...selected], [99, 1, 2, 3]);
sandbox.applyProductSelection(selected, filteredAcrossPages, false);
assert.deepEqual([...selected], [99]);

console.log('product selection check passed');
