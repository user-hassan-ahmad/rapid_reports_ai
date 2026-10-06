import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import ReportResponseViewer from './ReportResponseViewer.svelte';

const REPORT = `FINDINGS:
A mass.

IMPRESSION:
1. Cord compression at T7.
2. Urgent neurosurgical review recommended.

Dr A Consultant`;

const OPTIONS = [
	{ id: 'opt0', kind: 'impression' as const, sentence: 'T9 disease abuts the cord.', reason: '' },
	{ id: 'opt1', kind: 'recommendation' as const, sentence: 'MRI brain is recommended.', reason: 'either way' }
];

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe('optional additions in the report viewer', () => {
	it('clears the unsaved-changes bar when ticking and unticking restores the report', async () => {
		render(ReportResponseViewer, { visible: true, response: REPORT, options: OPTIONS });
		await pause(300);
		const box = page.getByRole('checkbox').first();
		await box.click();
		await pause(300);
		await expect.element(page.getByTestId('unsaved-status')).toBeInTheDocument();
		await box.click();
		await pause(600);
		expect(document.querySelector('[data-testid="unsaved-status"]')).toBeNull();
	});
});
