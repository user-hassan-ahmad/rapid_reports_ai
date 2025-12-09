<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import logo from '$lib/assets/radflow-logo.png';
	import bgCircuit from '$lib/assets/background circuit board effect.png';
	import { API_URL } from '$lib/config';

	let error = '';
	let message = '';
	let loading = true;
	let token = '';

	onMount(async () => {
		// Extract token from URL
		const urlParams = new URLSearchParams(window.location.search);
		const tokenParam = urlParams.get('token');

		if (!tokenParam) {
			error = 'Invalid verification link';
			loading = false;
			return;
		}

		token = tokenParam;

		// Auto-verify
		try {
			const res = await fetch(`${API_URL}/api/auth/verify-email`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ token })
			});

			const data = await res.json();

			if (res.ok && data.success) {
				message = 'Email verified successfully! Redirecting to login...';
				setTimeout(() => {
					goto('/login');
				}, 2000);
			} else {
				error = data.error || 'Failed to verify email';
			}
		} catch (err) {
			error = 'Failed to connect to server';
		} finally {
			loading = false;
		}
	});
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
			<h2 class="text-2xl font-bold mb-6 text-white">Verify Email</h2>

		{#if loading}
			<div class="text-center">
				<p class="text-gray-400">Verifying your email...</p>
			</div>
		{:else if error}
			<div class="mb-4 p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg">
				{error}
			</div>
		{:else if message}
			<div class="mb-4 p-3 bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg">
				{message}
			</div>
		{/if}

		<div class="mt-4 text-sm text-center text-gray-400">
			<a href="/login" class="text-purple-400 hover:text-purple-300 underline">← Back to Login</a>
		</div>
		</div>
	</div>
</div>

