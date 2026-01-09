<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { isAuthenticated } from '$lib/stores/auth';
	import logo from '$lib/assets/radflow-logo.png';
	import bgCircuit from '$lib/assets/background circuit board effect.png';

	// Redirect to app if already authenticated
	onMount(() => {
		if ($isAuthenticated) {
			goto('/');
		}
	});

	let expandedCardIndex = null;
	let disclaimerExpanded = false;

	let features = [
		{
			icon: 'lightning',
			iconColor: 'from-yellow-400 to-orange-500',
			title: 'Instant Report Generation',
			description: 'Paste your raw findings and get a complete, structured NHS-standard report in seconds',
			details: 'Transform unstructured findings into professional radiology reports instantly. Just add your observations, clinical history, and scan type—the AI structures it into proper sections (COMPARISON, LIMITATIONS, FINDINGS, IMPRESSION) with appropriate medical language. Or create custom templates for your specific workflow. Includes voice dictation support.',
			additionalFeatures: ['Instant structuring from raw findings', 'Custom template creation', 'Voice dictation support']
		},
		{
			icon: 'wand',
			iconColor: 'from-purple-400 to-pink-500',
			title: 'Template Wizard',
			description: 'Build custom templates with our guided step-by-step wizard—no technical knowledge required',
			details: 'Our intuitive wizard guides you through scan information, section configuration, findings setup, and impression details. Organize templates with tags, pin your favorites, and fine-tune every aspect of your reporting workflow.',
			additionalFeatures: ['Step-by-step guidance', 'Tag organization', 'Template customization']
		},
		{
			icon: 'shield',
			iconColor: 'from-green-400 to-emerald-500',
			title: 'Smart Audit & Quality Control',
			description: 'Automatically detect missing sections and incomplete information in your reports',
			details: 'Our intelligent audit system scans structured template reports and highlights unfilled sections, missing measurements, and empty variables. Get instant visual indicators with easy options to fill manually or request AI assistance. Includes contextual clinical guidelines for findings.',
			additionalFeatures: ['Automatic flagging', 'Clinical guidelines access', 'AI-assisted completion']
		},
		{
			icon: 'chat',
			iconColor: 'from-blue-400 to-cyan-500',
			title: 'AI Chat & Direct Edits',
			description: 'Explore your reports through conversation and apply precise AI-suggested edits',
			details: 'Chat with your report to explore findings, ask questions, and get recommendations. The AI proposes specific edits that you review and apply with one click. Perfect for refining reports and exploring alternatives.',
			additionalFeatures: ['Conversational exploration', 'Surgical edits', 'Edit proposals']
		},
		{
			icon: 'compare',
			iconColor: 'from-indigo-400 to-purple-500',
			title: 'Comparison & Version Control',
			description: 'Track changes between report versions and maintain complete history',
			details: 'Compare different versions to see what changed. The comparison tool identifies new, changed, and stable findings. Every report maintains full version history with the ability to restore any previous version.',
			additionalFeatures: ['Version comparison', 'Change tracking', 'Complete history']
		},
		{
			icon: 'lock',
			iconColor: 'from-red-400 to-pink-500',
			title: 'Secure & Private',
			description: 'Your sensitive medical data is protected with encryption and secure authentication',
			details: 'Data is encrypted at rest and in transit. We follow best practices for medical data security and privacy. Built with confidentiality in mind.',
			additionalFeatures: ['Data encryption', 'Secure authentication', 'Privacy-focused']
		}
	];

	let stats = [
		{ value: 'Beta', label: 'Early Access', description: 'Currently in active development' },
		{ value: 'Open', label: 'Free to Try', description: 'No payment required' },
		{ value: 'AI-First', label: 'Enhancement', description: 'Intelligent assistance' }
	];
	
	let howItWorks = [
		{
			step: '1',
			title: 'Choose Your Method',
			description: 'Generate instant reports from raw findings or create reusable custom templates with our wizard',
			iconColor: 'from-purple-400 to-blue-400'
		},
		{
			step: '2',
			title: 'Input Findings',
			description: 'Enter your findings via text or voice dictation. Our system understands medical terminology',
			iconColor: 'from-blue-400 to-cyan-400'
		},
		{
			step: '3',
			title: 'AI Enhancement',
			description: 'Review AI-suggested guidelines, audit results, and quality checks for your report',
			iconColor: 'from-cyan-400 to-green-400'
		},
		{
			step: '4',
			title: 'Refine & Finalize',
			description: 'Use chat to explore alternatives, apply edits, and finalize your report with confidence',
			iconColor: 'from-green-400 to-emerald-400'
		}
	];

	function toggleCard(index) {
		expandedCardIndex = expandedCardIndex === index ? null : index;
	}
	
	function isCardExpanded(index) {
		return expandedCardIndex === index;
	}
</script>

<div class="min-h-screen bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 relative overflow-hidden">
	<!-- Background Circuit Board Overlay -->
	<div class="fixed inset-0 pointer-events-none z-0">
		<!-- Vignette effect -->
		<div class="absolute inset-0" style="background: radial-gradient(ellipse at center, transparent 0%, rgba(0,0,0,0.4) 70%, rgba(0,0,0,0.7) 100%);"></div>
		<!-- Circuit board pattern -->
		<div class="absolute inset-0 opacity-20 mix-blend-overlay">
			<img src={bgCircuit} alt="" class="w-full h-full object-cover" />
		</div>
		<!-- Animated gradient orbs -->
		<div class="absolute top-0 left-1/4 w-96 h-96 bg-purple-500/20 rounded-full blur-3xl animate-pulse"></div>
		<div class="absolute bottom-0 right-1/4 w-96 h-96 bg-blue-500/20 rounded-full blur-3xl animate-pulse" style="animation-delay: 1s;"></div>
	</div>

	<!-- Navigation -->
	<nav class="relative z-10 px-6 py-6 flex items-center justify-between max-w-7xl mx-auto">
		<div class="flex items-center space-x-3">
			<img src={logo} alt="RadFlow" class="h-20 w-auto" />
			<span class="text-2xl font-bold text-white">RadFlow</span>
		</div>
		<div class="flex items-center space-x-4">
			<a href="/login" class="text-gray-300 hover:text-white transition-colors">Login</a>
			<a href="/register" class="btn-primary">Get Started</a>
		</div>
	</nav>

	<!-- Hero Section -->
	<section class="relative z-10 px-6 py-20 text-center max-w-5xl mx-auto">
		<div class="mb-8 animate-fade-in">
			<!-- Beta Badge -->
			<div class="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-purple-500/10 border border-purple-500/20 mb-6">
				<span class="relative flex h-2 w-2">
					<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75"></span>
					<span class="relative inline-flex rounded-full h-2 w-2 bg-purple-500"></span>
				</span>
				<span class="text-sm font-medium text-purple-300">Beta - Early Access Available</span>
			</div>
			
			<h1 class="text-5xl md:text-7xl font-bold text-white mb-6 leading-tight">
				Your AI
				<span class="bg-gradient-to-r from-purple-400 via-blue-400 to-purple-400 bg-clip-text text-transparent animate-gradient">
					Radiology Reporting Copilot
				</span>
			</h1>
			<p class="text-xl md:text-2xl text-gray-300 mb-8 max-w-3xl mx-auto leading-relaxed">
				Transform raw findings into structured NHS-standard reports instantly. Create custom templates effortlessly. Enhance every report with AI-powered clinical intelligence.
			</p>
			<div class="flex flex-col sm:flex-row items-center justify-center gap-4">
				<a href="/register" class="btn-primary text-lg px-8 py-4 font-semibold">
					Try It Out →
				</a>
				<a href="/login" class="btn-secondary text-lg px-8 py-4">
					Sign In
				</a>
			</div>
			<p class="text-sm text-gray-400 mt-4">
				Currently in beta · Free to use · No payment required
			</p>
		</div>

		<!-- Stats -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-16 max-w-3xl mx-auto">
			{#each stats as stat}
				<div class="card-dark text-center">
					<div class="text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-blue-400 mb-2">
						{stat.value}
					</div>
					<div class="text-lg font-semibold text-white mb-1">{stat.label}</div>
					<div class="text-sm text-gray-400">{stat.description}</div>
				</div>
			{/each}
		</div>
	</section>

	<!-- Features Section -->
	<section id="features" class="relative z-10 px-6 py-20 max-w-7xl mx-auto scroll-mt-20">
		<div class="text-center mb-16">
			<h2 class="text-4xl md:text-5xl font-bold text-white mb-4">
				Core
				<span class="bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
					Features
				</span>
			</h2>
			<p class="text-xl text-gray-400 max-w-2xl mx-auto">
				Everything you need to generate, enhance, and manage radiology reports with AI-powered intelligence
			</p>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
			{#each features as feature, i}
				{@const idx = i}
				{@const isExpanded = expandedCardIndex === idx}
				<div 
					class="template-card group cursor-pointer transform transition-all duration-300 hover:scale-105 hover:shadow-2xl hover:shadow-purple-500/20 relative overflow-hidden"
					class:expanded={isExpanded}
					onclick={() => toggleCard(idx)}
					role="button"
					tabindex="0"
					onkeydown={(e) => e.key === 'Enter' && toggleCard(idx)}
				>
					<div class="flex items-start justify-between mb-4">
						<div class="w-14 h-14 rounded-xl bg-gradient-to-br {feature.iconColor} flex items-center justify-center shadow-lg">
							{#if feature.icon === 'lightning'}
								<svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
								</svg>
							{:else if feature.icon === 'wand'}
								<svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
								</svg>
							{:else if feature.icon === 'shield'}
								<svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
								</svg>
							{:else if feature.icon === 'chat'}
								<svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
								</svg>
							{:else if feature.icon === 'compare'}
								<svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
								</svg>
							{:else if feature.icon === 'lock'}
								<svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
								</svg>
							{/if}
						</div>
						<button 
							class="text-gray-400 hover:text-white transition-colors text-xl font-bold w-6 h-6 flex items-center justify-center"
							onclick={(e) => { e.stopPropagation(); toggleCard(idx); }}
						>
							{isExpanded ? '−' : '+'}
						</button>
					</div>
					<h3 class="text-xl font-bold text-white mb-3">{feature.title}</h3>
					<p class="text-gray-400 leading-relaxed mb-2">{feature.description}</p>
					<div 
						class="overflow-hidden transition-all duration-500 ease-in-out"
						style="max-height: {isExpanded ? '500px' : '0px'}; opacity: {isExpanded ? '1' : '0'};"
					>
						<div class="pt-4 border-t border-white/10 mt-4">
							<p class="text-gray-300 leading-relaxed mb-4">{feature.details}</p>
							{#if feature.additionalFeatures}
								<div class="space-y-2">
									{#each feature.additionalFeatures as item}
										<div class="flex items-center gap-2 text-sm text-gray-400">
											<svg class="w-4 h-4 text-green-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
											</svg>
											<span>{item}</span>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		</div>
	</section>

	<!-- How It Works Section -->
	<section id="how-it-works" class="relative z-10 px-6 py-20 max-w-6xl mx-auto scroll-mt-20">
		<div class="text-center mb-16">
			<h2 class="text-4xl md:text-5xl font-bold text-white mb-4">
				How
				<span class="bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
					It Works
				</span>
			</h2>
			<p class="text-xl text-gray-400 max-w-2xl mx-auto">
				A simple, streamlined workflow from input to finalized report
			</p>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
			{#each howItWorks as step}
				<div class="relative">
					<!-- Step number -->
					<div class="mb-6">
						<div class="w-16 h-16 rounded-2xl bg-gradient-to-br {step.iconColor} flex items-center justify-center shadow-xl">
							<span class="text-2xl font-bold text-white">{step.step}</span>
						</div>
					</div>
					
					<!-- Content -->
					<h3 class="text-xl font-bold text-white mb-3">{step.title}</h3>
					<p class="text-gray-400 leading-relaxed">{step.description}</p>
					
					<!-- Connector arrow (hidden on last item and mobile) -->
					{#if parseInt(step.step) < howItWorks.length}
						<div class="hidden lg:block absolute top-8 -right-4 w-8 h-8">
							<svg class="w-full h-full text-purple-500/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
							</svg>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	</section>

	<!-- Beta Testimonial / Status Section -->
	<section class="relative z-10 px-6 py-20 max-w-4xl mx-auto">
		<div class="card-dark text-center">
			<div class="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 mb-6">
				<svg class="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
				</svg>
			</div>
			<h3 class="text-2xl font-bold text-white mb-4">We're Building in the Open</h3>
			<p class="text-gray-300 mb-6 max-w-2xl mx-auto leading-relaxed">
				RadFlow is currently in active beta development. We're working closely with early users to refine features and improve the experience. Your feedback helps shape the future of this platform.
			</p>
			<div class="flex flex-wrap items-center justify-center gap-4 text-sm text-gray-400">
				<div class="flex items-center gap-2">
					<svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
					</svg>
					<span>Regular updates</span>
				</div>
				<div class="flex items-center gap-2">
					<svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
					</svg>
					<span>Community-driven</span>
				</div>
				<div class="flex items-center gap-2">
					<svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
					</svg>
					<span>No payment required</span>
				</div>
			</div>
		</div>
	</section>

	<!-- CTA Section -->
	<section class="relative z-10 px-6 py-20 max-w-4xl mx-auto text-center">
		<div class="card-dark relative overflow-hidden">
			<!-- Background gradient -->
			<div class="absolute inset-0 bg-gradient-to-r from-purple-600/20 to-blue-600/20"></div>
			<div class="relative z-10">
				<h2 class="text-4xl md:text-5xl font-bold text-white mb-6">
					Ready to Try RadFlow?
				</h2>
				<p class="text-xl text-gray-300 mb-8 max-w-2xl mx-auto">
					Join early users testing RadFlow to streamline radiology reporting. Transform raw findings into structured reports instantly, audit for completeness, and enhance quality with AI-powered assistance.
				</p>
				<div class="flex flex-col sm:flex-row items-center justify-center gap-4">
					<a href="/register" class="btn-primary text-lg px-8 py-4 font-semibold">
						Try It Out →
					</a>
					<a href="/login" class="btn-secondary text-lg px-8 py-4">
						Sign In
					</a>
				</div>
				<p class="text-sm text-gray-400 mt-6">
					Beta access · No commitment · Free while in development
				</p>
			</div>
		</div>
	</section>

	<!-- Footer -->
	<footer class="relative z-10 px-6 py-12 border-t border-white/10">
		<div class="max-w-7xl mx-auto">
			<!-- Footer Grid -->
			<div class="grid grid-cols-1 md:grid-cols-4 gap-8 mb-12">
				<!-- Brand Column -->
				<div class="md:col-span-1">
					<div class="flex items-center space-x-3 mb-4">
						<img src={logo} alt="RadFlow" class="h-12 w-auto" />
						<span class="text-lg font-semibold text-white">RadFlow</span>
					</div>
					<p class="text-sm text-gray-400 mb-4">
						AI-powered radiology reporting copilot for modern radiologists.
					</p>
					<div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/20">
						<span class="relative flex h-2 w-2">
							<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75"></span>
							<span class="relative inline-flex rounded-full h-2 w-2 bg-purple-500"></span>
						</span>
						<span class="text-xs font-medium text-purple-300">Beta</span>
					</div>
				</div>

				<!-- Product Column -->
				<div>
					<h3 class="text-white font-semibold mb-4">Product</h3>
					<ul class="space-y-2 text-sm">
						<li><a href="#features" class="text-gray-400 hover:text-white transition-colors">Features</a></li>
						<li><a href="#how-it-works" class="text-gray-400 hover:text-white transition-colors">How It Works</a></li>
						<li><a href="/register" class="text-gray-400 hover:text-white transition-colors">Try Beta</a></li>
					</ul>
				</div>

				<!-- Get Started Column -->
				<div>
					<h3 class="text-white font-semibold mb-4">Get Started</h3>
					<ul class="space-y-2 text-sm">
						<li><a href="/register" class="text-gray-400 hover:text-white transition-colors">Create Account</a></li>
						<li><a href="/login" class="text-gray-400 hover:text-white transition-colors">Sign In</a></li>
						<li><a href="/forgot-password" class="text-gray-400 hover:text-white transition-colors">Reset Password</a></li>
					</ul>
				</div>

				<!-- About Column -->
				<div>
					<h3 class="text-white font-semibold mb-4">About</h3>
					<ul class="space-y-2 text-sm">
						<li><button onclick={() => disclaimerExpanded = !disclaimerExpanded} class="text-gray-400 hover:text-white transition-colors text-left">Legal Disclaimer</button></li>
						<li><span class="text-gray-400">Beta Version</span></li>
						<li><span class="text-gray-400">In Development</span></li>
					</ul>
				</div>
			</div>

			<!-- Footer Bottom -->
			<div class="pt-8 border-t border-white/5">
				<div class="text-sm text-gray-400 text-center">
					<p class="mb-1">© 2026 H&A LABS LTD | Company No. 16114480</p>
					<p class="text-gray-500">RadFlow is a product of H&A LABS LTD</p>
				</div>
			</div>

			
			<!-- Legal Disclaimer (Collapsible) -->
			{#if disclaimerExpanded}
				<div class="mt-8 pt-8 border-t border-white/5">
					<div class="max-w-4xl mx-auto">
						<div class="flex items-center justify-between mb-4">
							<h3 class="text-sm font-semibold text-white">Legal Disclaimer</h3>
							<button
								onclick={() => disclaimerExpanded = false}
								class="text-gray-400 hover:text-white transition-colors"
								aria-label="Close disclaimer"
							>
								<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						</div>
						<div class="text-xs text-gray-400 leading-relaxed space-y-3 max-h-96 overflow-y-auto pr-4">
							<p>
								<strong class="text-gray-300">Beta Software Notice:</strong> RadFlow is currently in beta. Features may change, and the application may contain bugs or incomplete functionality. Use for testing and evaluation purposes only.
							</p>
							<p>
								<strong class="text-gray-300">Intended Use:</strong> RadFlow is designed exclusively for use by qualified, licensed radiologists and medical professionals. This application is not intended for use by patients, non-medical personnel, or individuals without appropriate medical training and credentials.
							</p>
							<p>
								<strong class="text-gray-300">Professional Discretion Required:</strong> All content, suggestions, recommendations, and outputs generated by RadFlow are provided for informational and assistance purposes only. All advice, reports, and recommendations must be reviewed, validated, and used at the sole professional discretion of the licensed radiologist. RadFlow does not replace clinical judgment, professional expertise, or independent medical decision-making.
							</p>
							<p>
								<strong class="text-gray-300">No Medical Advice:</strong> RadFlow does not provide medical advice, diagnosis, or treatment recommendations. The application serves as a tool to assist radiologists in their professional work but does not constitute medical advice or establish a physician-patient relationship.
							</p>
							<p>
								<strong class="text-gray-300">Limitation of Liability:</strong> To the fullest extent permitted by law, RadFlow, its developers, operators, and affiliates (collectively, "we" or "us") disclaim all liability for any damages, losses, or adverse outcomes arising from the use or misuse of this application. This includes, but is not limited to, any direct, indirect, incidental, special, consequential, or punitive damages resulting from:
							</p>
							<ul class="list-disc list-inside ml-4 space-y-2 text-gray-500">
								<li>Errors, omissions, or inaccuracies in generated reports or content</li>
								<li>Decisions made based on information provided by RadFlow</li>
								<li>Failure to properly review, validate, or verify AI-generated content</li>
								<li>Technical failures, interruptions, or unavailability of the service</li>
								<li>Unauthorized access or use of the application</li>
							</ul>
							<p>
								<strong class="text-gray-300">User Responsibility:</strong> Users are solely responsible for ensuring the accuracy, completeness, and appropriateness of all reports, diagnoses, and medical decisions made using RadFlow. Users must comply with all applicable laws, regulations, and professional standards governing medical practice and patient care in their jurisdiction.
							</p>
							<p>
								<strong class="text-gray-300">No Warranties:</strong> RadFlow is provided "as is" without warranties of any kind, express or implied, including but not limited to warranties of merchantability, fitness for a particular purpose, accuracy, or non-infringement. We do not warrant that the application will be uninterrupted, error-free, or free from harmful components.
							</p>
							<p>
								<strong class="text-gray-300">Indemnification:</strong> By using RadFlow, you agree to indemnify, defend, and hold harmless RadFlow and its affiliates from any claims, damages, losses, liabilities, and expenses (including legal fees) arising from your use of the application, violation of these terms, or infringement of any rights of another party.
							</p>
							<p class="text-gray-500 italic mt-4">
								By accessing and using RadFlow, you acknowledge that you have read, understood, and agree to be bound by this disclaimer. If you do not agree with these terms, you must not use this application.
							</p>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</footer>
</div>

<style>
	/* Smooth scrolling for anchor links */
	:global(html) {
		scroll-behavior: smooth;
	}

	@keyframes fade-in {
		from {
			opacity: 0;
			transform: translateY(20px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	@keyframes gradient {
		0%, 100% {
			background-position: 0% 50%;
		}
		50% {
			background-position: 100% 50%;
		}
	}

	.animate-fade-in {
		animation: fade-in 0.8s ease-out;
	}

	.animate-gradient {
		background-size: 200% auto;
		animation: gradient 3s linear infinite;
	}

	.template-card.expanded {
		border-color: rgba(139, 92, 246, 0.6);
		box-shadow: 0 8px 32px rgba(139, 92, 246, 0.3);
	}

	/* Offset for smooth scroll to account for fixed header if any */
	.scroll-mt-20 {
		scroll-margin-top: 5rem;
	}
</style>
