<script>
	import { goto } from '$app/navigation';
	import logo from '$lib/assets/radflow-logo.png';
	import bgCircuit from '$lib/assets/background circuit board effect.png';
	import { API_URL } from '$lib/config';

	let email = '';
	let error = '';
	let loading = false;
	let message = '';

	async function handleResend() {
		loading = true;
		error = '';
		message = '';

		try {
			const res = await fetch(`${API_URL}/api/auth/resend-verification`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email })
			});

			const data = await res.json();

			if (res.ok && data.success) {
				message = data.message || 'Verification email sent! Please check your inbox and click the link to verify your email.';
			} else {
				error = data.error || 'Failed to send verification email';
			}
		} catch (err) {
			error = 'Failed to connect to server';
			console.error('Error:', err);
		} finally {
			loading = false;
		}
	}
</script>

<div class="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 p-4 relative overflow-hidden">
	<!-- Background Circuit Board Overlay -->
	<div class="absolute inset-0 pointer-events-none">
		<!-- Vignette effect - darker at edges, lighter in center -->
		<div class="absolute inset-0" style="background: radial-gradient(ellipse at center, transparent 0%, rgba(0,0,0,0.4) 70%, rgba(0,0,0,0.7) 100%);"></div>
		<!-- Circuit board pattern with overlay blend -->
		<div class="absolute inset-0 opacity-30 mix-blend-overlay">
			<img src={bgCircuit} alt="" class="w-full h-full object-cover" />
		</div>
	</div>
	<div class="w-full max-w-md relative z-10">
		<!-- App Logo -->
		<div class="mb-8 text-center">
			<div class="flex justify-center">
				<img src={logo} alt="RadFlow" class="h-40 w-auto" />
			</div>
		</div>

		<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl shadow-[0_8px_32px_rgba(139,92,246,0.1)] p-8">
			<h2 class="text-2xl font-bold mb-6 text-white">Resend Verification Email</h2>

		{#if error}
			<div class="mb-4 p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg">
				{error}
			</div>
		{/if}

		{#if message}
			<div class="mb-4 p-3 bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg">
				{message}
			</div>
		{/if}

		{#if !message}
			<p class="mb-6 text-gray-400">
				Enter your email address and we'll send you a new verification link.
			</p>

			<form onsubmit={(e) => { e.preventDefault(); handleResend(); }}>
				<div class="mb-6">
					<label class="block text-sm font-medium text-gray-300 mb-1">
						Email Address
					</label>
					<input
						type="email"
						bind:value={email}
						required
						class="input-dark"
						placeholder="you@example.com"
					/>
				</div>

				<button
					type="submit"
					disabled={loading}
					class="btn-primary w-full"
				>
					{loading ? 'Sending...' : 'Resend Verification Email'}
				</button>
			</form>
		{/if}

		<div class="mt-4 text-sm text-center text-gray-400">
			<a href="/login" class="text-purple-400 hover:text-purple-300 underline">← Back to Login</a>
		</div>
		</div>
	</div>
</div>

