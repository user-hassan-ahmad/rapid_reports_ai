<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { isAuthenticated } from '$lib/stores/auth';
	import logo from '$lib/assets/radflow-logo.png';
	import bgCircuit from '$lib/assets/background circuit board effect.png';
	import { API_URL } from '$lib/config';

	let email = '';
	let password = '';
	let fullName = '';
	let role = '';
	let institution = '';
	let signupReason = '';
	let error = '';
	let loading = false;
	let message = '';

	const ROLE_OPTIONS = [
		{ value: 'consultant_radiologist', label: 'Consultant radiologist' },
		{ value: 'registrar', label: 'Registrar' },
		{ value: 'reporting_radiographer', label: 'Reporting radiographer' },
		{ value: 'medical_student', label: 'Medical student' },
		{ value: 'other_healthcare_professional', label: 'Other healthcare professional' },
		{ value: 'other', label: 'Other' }
	];

	// Redirect if already logged in
	onMount(() => {
		if ($isAuthenticated) {
			goto('/');
		}
	});

	function validate() {
		if (!fullName.trim()) return 'Please enter your full name.';
		if (!role) return 'Please select your role.';
		if (!institution.trim()) return 'Please enter your institution.';
		if (signupReason.trim().length < 10) return 'Please tell us a bit more (at least 10 characters).';
		if (signupReason.length > 1000) return 'Reason is too long (max 1000 characters).';
		return '';
	}

	async function handleRegister() {
		loading = true;
		error = '';
		message = '';

		const clientErr = validate();
		if (clientErr) {
			error = clientErr;
			loading = false;
			return;
		}

		try {
			const res = await fetch(`${API_URL}/api/auth/register`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					email,
					password,
					full_name: fullName,
					role,
					institution,
					signup_reason: signupReason
				})
			});

			const data = await res.json();

			if (res.ok && data.success) {
				message = data.message || "Thanks — your account is pending admin approval. We'll email you when it's approved.";
			} else if (res.status === 422) {
				error = 'Please check the form — some fields look invalid.';
			} else {
				error = data.error || 'Registration failed. Please try again.';
			}
		} catch (err) {
			const errorMessage = err instanceof Error ? err.message : String(err);
			if (errorMessage.includes('Failed to fetch') || errorMessage.includes('NetworkError')) {
				error = 'Failed to connect. Please try again.';
			} else {
				error = 'Registration failed. Please try again.';
			}
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
			<h2 class="text-2xl font-bold mb-6 text-white">Create Account</h2>

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
			<form onsubmit={(e) => { e.preventDefault(); handleRegister(); }}>
				<div class="mb-4">
					<label class="block text-sm font-medium text-gray-300 mb-1">
						Full Name <span class="text-red-400">*</span>
					</label>
					<input
						type="text"
						bind:value={fullName}
						required
						minlength="1"
						maxlength="200"
						class="input-dark"
						placeholder="John Doe"
					/>
				</div>

				<div class="mb-4">
					<label class="block text-sm font-medium text-gray-300 mb-1">
						Email <span class="text-red-400">*</span>
					</label>
					<input
						type="email"
						bind:value={email}
						required
						class="input-dark"
						placeholder="you@example.com"
					/>
				</div>

				<div class="mb-4">
					<label class="block text-sm font-medium text-gray-300 mb-1">
						Role <span class="text-red-400">*</span>
					</label>
					<select bind:value={role} required class="input-dark">
						<option value="" disabled>Select your role…</option>
						{#each ROLE_OPTIONS as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
				</div>

				<div class="mb-4">
					<label class="block text-sm font-medium text-gray-300 mb-1">
						Institution <span class="text-red-400">*</span>
					</label>
					<input
						type="text"
						bind:value={institution}
						required
						minlength="1"
						maxlength="200"
						class="input-dark"
						placeholder="e.g. Guy's and St Thomas'"
					/>
				</div>

				<div class="mb-4">
					<label class="block text-sm font-medium text-gray-300 mb-1">
						Why do you want to use Radflow? <span class="text-red-400">*</span>
					</label>
					<textarea
						bind:value={signupReason}
						required
						minlength="10"
						maxlength="1000"
						rows="4"
						class="input-dark"
						placeholder="What made you try Radflow? What are you hoping to use it for?"
					></textarea>
					<p class="text-xs text-gray-500 mt-1">{signupReason.length} / 1000</p>
				</div>

				<div class="mb-6">
					<label class="block text-sm font-medium text-gray-300 mb-1">
						Password <span class="text-red-400">*</span>
					</label>
					<input
						type="password"
						bind:value={password}
						required
						minlength="8"
						class="input-dark"
						placeholder="••••••••"
					/>
					<p class="text-xs text-gray-500 mt-1">At least 8 characters</p>
				</div>

				<button
					type="submit"
					disabled={loading}
					class="btn-primary w-full"
				>
					{loading ? 'Creating account...' : 'Register'}
				</button>
			</form>
		{/if}

		<div class="mt-4 text-sm text-center text-gray-400">
			<p>Already have an account? <a href="/login" class="text-purple-400 hover:text-purple-300 underline">Login</a></p>
		</div>
		</div>
	</div>
</div>

