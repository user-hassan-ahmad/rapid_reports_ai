// Writes the TS outputs into the golden file the Python port is tested against (run once per change to the TS).
import { readFileSync, writeFileSync } from 'node:fs';
import { buildFindingsBlock, findingsHash, findingsText } from '../src/lib/hybrid-stack/regionState';

const path = process.argv[2];
const data = JSON.parse(readFileSync(path, 'utf8'));
for (const c of data.cases) {
	c.expected = {
		hash: findingsHash(c.units),
		text: findingsText(c.units, c.groups),
		block: c.gate ? buildFindingsBlock(c.units, c.groups, c.gate) : null
	};
}
writeFileSync(path, JSON.stringify(data, null, 2) + '\n');
