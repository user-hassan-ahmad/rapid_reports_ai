<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { login, isAuthenticated } from '$lib/stores/auth';
	import logo from '$lib/assets/radflow-logo.png';
	import bgCircuit from '$lib/assets/background circuit board effect.png';
	import { API_URL } from '$lib/config';

	let email = '';
	let password = '';
	let error = '';
	let loading = false;
	let showResendLink = false;

	// Redirect if already logged in
	onMount(() => {
		if ($isAuthenticated) {
			goto('/');
		}
	});

	async function handleLogin() {
		loading = true;
		error = '';
		showResendLink = false;

		try {
			// Use OAuth2PasswordRequestForm format
			const formData = new URLSearchParams();
			formData.append('username', email);
			formData.append('password', password);

			const res = await fetch(`${API_URL}/api/auth/login`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
				body: formData
			});

			const data = await res.json();

			if (res.ok && data.success) {
				console.log('✅ Login successful, token:', data.access_token ? 'received' : 'missing');
				login(data.access_token);
				console.log('🔄 Navigating to home page...');
				goto('/');
			} else {
				console.log('❌ Login failed:', data.error);
				error = data.error || 'Login failed';
				
				// Check if error is about email verification
				if (data.error && data.error.toLowerCase().includes('verify your email')) {
					showResendLink = true;
				}
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
		<!-- Back to Landing Link -->
		<div class="mb-4 text-center">
			<a href="/home" class="text-gray-400 hover:text-white transition-colors text-sm inline-flex items-center gap-2">
				← Back to Home
			</a>
		</div>

		<!-- App Logo -->
		<div class="mb-8 text-center">
			<div class="flex justify-center">
				<img src={logo} alt="RadFlow" class="h-56 w-auto" />
			</div>
		</div>

		<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl shadow-[0_8px_32px_rgba(139,92,246,0.1)] p-8">
			<h2 class="text-2xl font-bold mb-6 text-white">Login</h2>

		{#if error}
			<div class="mb-4 p-3 bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg">
				{error}
				
				{#if showResendLink}
					<div class="mt-3 pt-3 border-t border-red-500/30">
						<p class="text-sm mb-2 text-red-300">Didn't receive the verification email? Check your spam/junk folder.</p>
						<a href="/resend-verification" class="text-sm text-purple-400 hover:text-purple-300 underline font-medium">
							Resend verification email →
						</a>
					</div>
				{/if}
			</div>
		{/if}

		<form onsubmit={(e) => { e.preventDefault(); handleLogin(); }}>
			<div class="mb-4">
				<label class="block text-sm font-medium text-gray-300 mb-1">
					Email
				</label>
				<input
					type="email"
					bind:value={email}
					required
					class="input-dark"
					placeholder="you@example.com"
				/>
			</div>

			<div class="mb-6">
				<label class="block text-sm font-medium text-gray-300 mb-1">
					Password
				</label>
				<input
					type="password"
					bind:value={password}
					required
					class="input-dark"
					placeholder="••••••••"
				/>
			</div>

			<button
				type="submit"
				disabled={loading}
				class="btn-primary w-full"
			>
				{loading ? 'Logging in...' : 'Login'}
			</button>
		</form>

		<div class="mt-4 text-sm text-center text-gray-400">
			<p>Don't have an account? <a href="/register" class="text-purple-400 hover:text-purple-300 underline">Register</a></p>
			<p class="mt-2">
				<a href="/forgot-password" class="text-purple-400 hover:text-purple-300 underline">Forgot password?</a>
			</p>
		</div>
		</div>
	</div>
</div>

