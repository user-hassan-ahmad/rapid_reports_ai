/** The backend's text_hash: sha256(text) as hex, first 16 characters. */
export async function textHash(text: string): Promise<string> {
	const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text ?? ''));
	return [...new Uint8Array(buf)]
		.map((b) => b.toString(16).padStart(2, '0'))
		.join('')
		.slice(0, 16);
}
