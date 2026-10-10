// Chat replies are model text written in Markdown. They render as HTML (marked, as the app's other renderMarkdown
// helpers do) through a strict allowlist (DOMPurify, as SkillSheetCreator does): only text formatting, lists and
// http(s) links survive; scripts, handlers, styles, images, iframes and every other tag or attribute are dropped.
import DOMPurify from 'dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = ['p', 'br', 'strong', 'b', 'em', 'i', 'ul', 'ol', 'li', 'code', 'pre', 'blockquote', 'a', 'h4', 'h5', 'h6'];

let hooked = false;
function hook(): void {
	if (hooked) return;
	hooked = true;
	DOMPurify.addHook('afterSanitizeAttributes', (node) => {
		if (node.tagName !== 'A') return;
		const href = node.getAttribute('href') ?? '';
		let ok = false;
		try {
			ok = ['http:', 'https:'].includes(new URL(href).protocol);
		} catch {
			ok = false;
		}
		if (!ok) node.removeAttribute('href');
		else {
			node.setAttribute('target', '_blank');
			node.setAttribute('rel', 'noopener noreferrer');
		}
	});
}

/** Model Markdown → sanitised HTML for `{@html}`. Headings render no larger than h4 (it is a narrow rail). */
export function renderChatMarkdown(md: string | null | undefined): string {
	if (!md) return '';
	hook();
	const html = marked.parse(md.trim(), { gfm: true, breaks: false, async: false }) as string;
	const capped = html.replace(/<(\/?)h[1-3](\s|>)/g, '<$1h4$2');
	return DOMPurify.sanitize(capped, {
		ALLOWED_TAGS,
		ALLOWED_ATTR: ['href', 'target', 'rel'],
		ALLOW_DATA_ATTR: false
	});
}

/** Sources with an http(s) URL, deduplicated by URL (first title kept); entries with no URL are kept once by title. */
/** A readable label from a link: its last path segments and host ("Appendicitis management · cks.nice.org.uk"). */
function pageLabel(url: string): string | null {
	try {
		const u = new URL(url);
		const parts = u.pathname.split('/').filter(Boolean).filter((p) => !/^(topics?|pages?|guidance|en|www)$/i.test(p));
		const words = parts.slice(-2).join(' ').replace(/[-_]+/g, ' ').replace(/\.\w+$/, '').trim();
		const host = u.hostname.replace(/^www\./, '');
		return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)} · ${host}` : host;
	} catch {
		return null;
	}
}

export function dedupeSources<T extends { url?: string | null; title?: string | null }>(sources: readonly T[]): T[] {
	const seen = new Set<string>();
	const out: T[] = [];
	for (const s of sources) {
		const key = (s.url || '').trim().replace(/\/+$/, '').toLowerCase() || `title:${(s.title || '').trim().toLowerCase()}`;
		if (key === 'title:' || seen.has(key)) continue;
		seen.add(key);
		out.push(s);
	}
	// one title on several different links is a site's generic or block-page title (live: "CKS is only available
	// in the UK | NICE" ×3): it says nothing about the page, so label those by their link instead
	const titles = new Map<string, number>();
	for (const s of out) {
		const t = (s.title || '').trim().toLowerCase();
		if (t) titles.set(t, (titles.get(t) ?? 0) + 1);
	}
	return out.map((s) => {
		const t = (s.title || '').trim().toLowerCase();
		const label = t && (titles.get(t) ?? 0) > 1 && s.url ? pageLabel(s.url) : null;
		return label ? { ...s, title: label } : s;
	});
}
