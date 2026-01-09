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
	let expandedStyleExample = null; // 'concise', 'prose', or null
	let expandedWritingControl = null; // 'format', 'sequence', 'preferences', or null

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
			icon: 'book',
			iconColor: 'from-teal-400 to-cyan-500',
			title: 'Clinical Guidelines & Literature',
			description: 'Instant access to evidence-based guidelines, classifications, and differential diagnoses for your findings',
			details: 'For every finding in your report, get comprehensive clinical information: diagnostic overviews, classification systems (e.g., BI-RADS, Fleischner), standardized measurement protocols, imaging characteristics, differential diagnoses, and follow-up recommendations. All sourced from current medical literature with references.',
			additionalFeatures: ['Evidence-based guidelines', 'Classification systems', 'Differential diagnoses', 'Follow-up protocols']
		},
		{
			icon: 'shield',
			iconColor: 'from-green-400 to-emerald-500',
			title: 'Smart Audit & Quality Control',
			description: 'Automatically detect missing sections and incomplete information in your reports',
			details: 'Our intelligent audit system scans structured template reports and highlights unfilled sections, missing measurements, and empty variables. Get instant visual indicators with easy options to fill manually or request AI assistance.',
			additionalFeatures: ['Automatic flagging', 'Missing measurement detection', 'AI-assisted completion']
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
			title: 'Intelligent Interval Comparison',
			description: 'AI-powered analysis of interval changes between current and prior scans with automatic report updates',
			details: 'Compare your current report against prior studies to automatically identify new findings, disease progression, stable pathology, and resolved abnormalities. The AI precisely tracks measurements over time, calculates growth rates, and generates a revised report that properly documents interval changes with dates and scan types. Also includes version-to-version comparison with visual diff highlighting to track your edits.',
			additionalFeatures: ['Automated interval change detection', 'Measurement tracking & trends', 'AI-generated comparison reports', 'Version history with visual diffs']
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
	
	function toggleStyleExample(style) {
		expandedStyleExample = expandedStyleExample === style ? null : style;
	}
	
	function toggleWritingControl(control) {
		expandedWritingControl = expandedWritingControl === control ? null : control;
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
						{:else if feature.icon === 'book'}
							<svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
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

	<!-- Template Customization Feature Highlight -->
	<section class="relative z-10 px-6 py-20 max-w-7xl mx-auto">
		<div class="text-center mb-12">
			<div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/20 mb-4">
				<svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
				</svg>
				<span class="text-xs font-medium text-purple-300">Complete Control</span>
			</div>
			<h2 class="text-3xl md:text-4xl font-bold text-white mb-4">
				Templates That Adapt to Your Workflow
			</h2>
			<p class="text-lg text-gray-300 max-w-3xl mx-auto">
				Choose how AI interprets your templates and fine-tune the writing style to match your preferences—from flexible prose to strict fill-in-the-blanks
			</p>
		</div>

		<!-- Content Style Templates -->
		<div class="mb-12">
			<h3 class="text-xl font-semibold text-white mb-6 text-center">Content Style Templates</h3>
			<div class="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
				<!-- Normal Template -->
				<div class="card-dark group hover:border-purple-500/40 transition-all duration-300">
					<div class="text-4xl mb-3">📋</div>
					<h4 class="text-lg font-bold text-white mb-2">Normal Template</h4>
					<p class="text-sm text-gray-400 mb-4">Paste a normal report as your template—AI learns your language and adapts it to describe actual findings</p>
					<div class="space-y-2 text-xs text-gray-500">
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>Use any normal report as template</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>AI maintains your voice</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>Best for general reporting</span>
						</div>
					</div>
				</div>

				<!-- Guided Template -->
				<div class="card-dark group hover:border-purple-500/40 transition-all duration-300">
					<div class="text-4xl mb-3">📝</div>
					<h4 class="text-lg font-bold text-white mb-2">Guided Template</h4>
					<p class="text-sm text-gray-400 mb-4">Normal template + embedded // comments that guide AI on what to assess and how to interpret findings</p>
					<div class="space-y-2 text-xs text-gray-500">
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>Same as Normal Template</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-purple-400 mt-0.5">+</span>
							<span>// comments provide AI context</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>Helps AI make smart adaptations</span>
						</div>
					</div>
				</div>

				<!-- Structured Template -->
				<div class="card-dark group hover:border-purple-500/40 transition-all duration-300">
					<div class="text-4xl mb-3">📐</div>
					<h4 class="text-lg font-bold text-white mb-2">Structured Fill-In</h4>
					<p class="text-sm text-gray-400 mb-4">Strict placeholders: {`{VAR}`}, xxx, [opt1/opt2] for precise control</p>
					<div class="space-y-2 text-xs text-gray-500">
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>EXACT template preservation</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>Smart form-filling</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>High fidelity output</span>
						</div>
					</div>
				</div>

				<!-- Checklist -->
				<div class="card-dark group hover:border-purple-500/40 transition-all duration-300">
					<div class="text-4xl mb-3">✓</div>
					<h4 class="text-lg font-bold text-white mb-2">Systematic Checklist</h4>
					<p class="text-sm text-gray-400 mb-4">Simple bullet list—AI expands each item systematically</p>
					<div class="space-y-2 text-xs text-gray-500">
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>Template is just a list</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>AI covers each structure</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-green-400 mt-0.5">✓</span>
							<span>Nothing gets missed</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Writing Style Optimizations -->
		<div class="card-dark">
			<h3 class="text-xl font-semibold text-white mb-4">Writing Style Optimizations</h3>
			<p class="text-gray-300 mb-8">
				Fine-tune how AI generates your reports with granular control over writing style, format, organization, and clinical preferences.
			</p>
			
			<!-- Primary Choice: Template Fidelity vs Custom Style -->
			<div class="mb-8 p-6 bg-gradient-to-r from-purple-500/10 to-indigo-500/10 border border-purple-500/30 rounded-xl">
				<div class="flex items-center gap-3 mb-4">
					<div class="w-10 h-10 rounded-lg bg-purple-500/20 border border-purple-500/40 flex items-center justify-center">
						<span class="text-xl">🎯</span>
					</div>
					<div class="flex-1">
						<div class="text-white font-semibold mb-1">Primary Style Control</div>
						<div class="text-sm text-gray-400">Choose how AI interprets your template language</div>
					</div>
				</div>
				
				<div class="grid md:grid-cols-2 gap-4">
					<div class="bg-black/20 rounded-lg p-4 border border-white/10">
						<div class="flex items-center gap-2 mb-2">
							<div class="w-2 h-2 rounded-full bg-purple-400"></div>
							<span class="text-white font-medium">Follow Template Style</span>
						</div>
						<p class="text-sm text-gray-400 mb-3">
							AI matches your template's established voice and sentence structure
						</p>
						<div class="text-xs text-gray-500 italic">
							Best for maintaining consistent institutional style
						</div>
					</div>
					
					<div class="bg-black/20 rounded-lg p-4 border border-white/10">
						<div class="flex items-center gap-2 mb-2">
							<div class="w-2 h-2 rounded-full bg-cyan-400"></div>
							<span class="text-white font-medium">Choose Writing Style</span>
						</div>
						<p class="text-sm text-gray-400 mb-3">
							Pick between 
							<button 
								onclick={() => toggleStyleExample('concise')} 
								class="text-blue-300 font-medium hover:text-blue-200 underline decoration-dotted transition-colors"
							>
								Concise
							</button> 
							(essentials only) or 
							<button 
								onclick={() => toggleStyleExample('prose')} 
								class="text-purple-300 font-medium hover:text-purple-200 underline decoration-dotted transition-colors"
							>
								Prose
							</button> 
							(balanced detail)
						</p>
						<div class="text-xs text-gray-500 italic">
							Gives you direct control over verbosity level
						</div>
						
						<!-- Expandable Examples -->
						{#if expandedStyleExample === 'concise'}
							<div class="mt-4 p-3 bg-gradient-to-r from-blue-500/10 to-cyan-500/10 border border-blue-500/30 rounded-lg animate-fade-in">
								<div class="flex items-center gap-2 mb-2">
									<span class="text-xs font-semibold text-blue-300">Concise Example</span>
									<span class="text-xs px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-300">⚡</span>
								</div>
								<p class="text-xs text-gray-300 leading-relaxed mb-1.5">
									Large filling defects in the right pulmonary artery extending to segmental branches. Additional defect in the left lower lobe. RV dilated, RV/LV ratio 1.3.
								</p>
								<div class="text-xs text-gray-500 italic">Essentials only • Brief</div>
							</div>
						{/if}
						
						{#if expandedStyleExample === 'prose'}
							<div class="mt-4 p-3 bg-gradient-to-r from-purple-500/10 to-pink-500/10 border border-purple-500/30 rounded-lg animate-fade-in">
								<div class="flex items-center gap-2 mb-2">
									<span class="text-xs font-semibold text-purple-300">Prose Example</span>
									<span class="text-xs px-1.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300">⚖️</span>
								</div>
								<p class="text-xs text-gray-300 leading-relaxed mb-1.5">
									Large filling defects are present in the right main pulmonary artery, extending into segmental branches. An additional filling defect is identified in the left lower lobe. The right ventricle is moderately dilated with an RV/LV ratio of 1.3.
								</p>
								<div class="text-xs text-gray-500 italic">Balanced • Natural flow</div>
							</div>
						{/if}
					</div>
				</div>
			</div>
			
			<!-- Additional Controls (Expandable) -->
			<div class="grid md:grid-cols-3 gap-4">
				<!-- Format Options -->
				<button 
					onclick={() => toggleWritingControl('format')}
					class="flex items-start gap-3 p-4 bg-white/5 rounded-lg border border-white/10 hover:border-purple-500/40 hover:bg-white/10 transition-all duration-300 cursor-pointer text-left group"
				>
					<div class="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center group-hover:bg-purple-500/20 transition-colors">
						<span class="text-base">📝</span>
					</div>
					<div class="flex-1">
						<div class="text-white font-medium text-sm mb-1 flex items-center gap-2">
							Format Options
							<svg class="w-4 h-4 text-gray-400 transition-transform {expandedWritingControl === 'format' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
							</svg>
						</div>
						<div class="text-xs text-gray-400">Prose, bullets, or numbered lists</div>
					</div>
				</button>
				
				<!-- Finding Sequence -->
				<button 
					onclick={() => toggleWritingControl('sequence')}
					class="flex items-start gap-3 p-4 bg-white/5 rounded-lg border border-white/10 hover:border-purple-500/40 hover:bg-white/10 transition-all duration-300 cursor-pointer text-left group"
				>
					<div class="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center group-hover:bg-purple-500/20 transition-colors">
						<span class="text-base">📋</span>
					</div>
					<div class="flex-1">
						<div class="text-white font-medium text-sm mb-1 flex items-center gap-2">
							Finding Sequence
							<svg class="w-4 h-4 text-gray-400 transition-transform {expandedWritingControl === 'sequence' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
							</svg>
						</div>
						<div class="text-xs text-gray-400">Clinical priority or template order</div>
					</div>
				</button>
				
				<!-- Clinical Preferences -->
				<button 
					onclick={() => toggleWritingControl('preferences')}
					class="flex items-start gap-3 p-4 bg-white/5 rounded-lg border border-white/10 hover:border-purple-500/40 hover:bg-white/10 transition-all duration-300 cursor-pointer text-left group"
				>
					<div class="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center group-hover:bg-purple-500/20 transition-colors">
						<span class="text-base">🔍</span>
					</div>
					<div class="flex-1">
						<div class="text-white font-medium text-sm mb-1 flex items-center gap-2">
							Clinical Preferences
							<svg class="w-4 h-4 text-gray-400 transition-transform {expandedWritingControl === 'preferences' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
							</svg>
						</div>
						<div class="text-xs text-gray-400">DDx, recommendations, headers</div>
					</div>
				</button>
			</div>
			
			<!-- Expanded Control Details -->
			{#if expandedWritingControl === 'format'}
				<div class="mt-4 p-4 bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/30 rounded-lg animate-fade-in">
					<div class="text-white font-semibold mb-3">Format Options</div>
					<div class="grid md:grid-cols-3 gap-3">
						<div class="bg-black/20 rounded p-3 border border-white/10">
							<div class="text-sm font-medium text-purple-300 mb-1">Prose Paragraphs</div>
							<div class="text-xs text-gray-400">Natural flowing text with complete sentences</div>
						</div>
						<div class="bg-black/20 rounded p-3 border border-white/10">
							<div class="text-sm font-medium text-blue-300 mb-1">Bullet Points</div>
							<div class="text-xs text-gray-400">• Structured list format for clarity</div>
						</div>
						<div class="bg-black/20 rounded p-3 border border-white/10">
							<div class="text-sm font-medium text-cyan-300 mb-1">Numbered Lists</div>
							<div class="text-xs text-gray-400">1. Sequential findings with priority</div>
						</div>
					</div>
				</div>
			{/if}
			
			{#if expandedWritingControl === 'sequence'}
				<div class="mt-4 p-4 bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/30 rounded-lg animate-fade-in">
					<div class="text-white font-semibold mb-3">Finding Sequence</div>
					<div class="grid md:grid-cols-2 gap-3">
						<div class="bg-black/20 rounded p-3 border border-white/10">
							<div class="text-sm font-medium text-orange-300 mb-1">Clinical Priority</div>
							<div class="text-xs text-gray-400">Critical findings first, then significant, then incidental</div>
						</div>
						<div class="bg-black/20 rounded p-3 border border-white/10">
							<div class="text-sm font-medium text-green-300 mb-1">Template Order</div>
							<div class="text-xs text-gray-400">Follows the exact structure of your template</div>
						</div>
					</div>
				</div>
			{/if}
			
			{#if expandedWritingControl === 'preferences'}
				<div class="mt-4 p-4 bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/30 rounded-lg animate-fade-in">
					<div class="text-white font-semibold mb-3">Clinical Preferences</div>
					<div class="space-y-2 text-sm text-gray-300">
						<div class="flex items-start gap-2">
							<span class="text-purple-400">•</span>
							<span><strong class="text-white">Differential Diagnosis:</strong> Include when needed, always, or never</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-purple-400">•</span>
							<span><strong class="text-white">Recommendations:</strong> Specialist referral, further workup, imaging follow-up</span>
						</div>
						<div class="flex items-start gap-2">
							<span class="text-purple-400">•</span>
							<span><strong class="text-white">Subsection Headers:</strong> Add anatomical headers (CHEST:, ABDOMEN:)</span>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</section>

	<!-- Interval Comparison Feature Highlight -->
	<section class="relative z-10 px-6 py-20 max-w-6xl mx-auto">
		<div class="card-dark relative overflow-hidden">
			<!-- Decorative gradient background -->
			<div class="absolute inset-0 bg-gradient-to-br from-indigo-600/10 via-purple-600/10 to-blue-600/10"></div>
			
			<div class="relative z-10 grid md:grid-cols-2 gap-8 items-center">
				<!-- Left: Content -->
				<div>
					<div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/20 mb-4">
						<svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
						</svg>
						<span class="text-xs font-medium text-indigo-300">Powerful Feature</span>
					</div>
					
					<h2 class="text-3xl md:text-4xl font-bold text-white mb-4">
						Automated Interval Change Analysis
					</h2>
					
					<p class="text-lg text-gray-300 mb-6 leading-relaxed">
						Upload prior scans and let AI automatically detect what's new, what's changed, and what's stable. Get precise measurement tracking, growth rate calculations, and a professionally formatted comparison report—all in seconds.
					</p>
					
					<div class="space-y-3">
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							</div>
							<div>
								<div class="text-white font-medium">Intelligent Finding Classification</div>
								<div class="text-sm text-gray-400">Automatically categorizes findings as new, changed, stable, or resolved</div>
							</div>
						</div>
						
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							</div>
							<div>
								<div class="text-white font-medium">Precise Measurement Tracking</div>
								<div class="text-sm text-gray-400">Track lesion sizes over time with automated growth rate calculations</div>
							</div>
						</div>
						
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							</div>
							<div>
								<div class="text-white font-medium">Professional Comparison Reports</div>
								<div class="text-sm text-gray-400">Generates properly formatted reports with prior dates and scan types</div>
							</div>
						</div>
					</div>
				</div>
				
				<!-- Right: Visual representation -->
				<div class="relative">
					<!-- Simulated comparison view -->
					<div class="relative space-y-3">
						<!-- Current Report Card -->
						<div class="bg-gradient-to-r from-blue-500/10 to-cyan-500/10 backdrop-blur-xl border border-blue-500/30 rounded-lg p-4">
							<div class="flex items-center justify-between mb-2">
								<span class="text-xs font-semibold text-blue-300">Current Report</span>
								<span class="text-xs text-gray-400">15/01/2026</span>
							</div>
							<div class="space-y-2 text-sm">
								<div class="flex items-start gap-2">
									<span class="text-green-400 font-bold text-xs mt-0.5">NEW</span>
									<span class="text-gray-300">3mm nodule in RLL</span>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-yellow-400 font-bold text-xs mt-0.5">CHANGED</span>
									<span class="text-gray-300">LUL nodule: 8mm → 11mm</span>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-gray-400 font-bold text-xs mt-0.5">STABLE</span>
									<span class="text-gray-300">No pleural effusion</span>
								</div>
							</div>
						</div>
						
						<!-- Comparison Arrow -->
						<div class="flex justify-center">
							<div class="w-8 h-8 rounded-full bg-purple-500/20 border border-purple-500/30 flex items-center justify-center">
								<svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
								</svg>
							</div>
						</div>
						
						<!-- Prior Report Card -->
						<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-lg p-4">
							<div class="flex items-center justify-between mb-2">
								<span class="text-xs font-semibold text-gray-400">Prior Report</span>
								<span class="text-xs text-gray-500">12/09/2025</span>
							</div>
							<div class="space-y-2 text-sm text-gray-400">
								<div>• LUL nodule: 8mm</div>
								<div>• No pleural effusion</div>
								<div>• No focal consolidation</div>
							</div>
						</div>
					</div>
					
					<!-- Decorative pulse animation -->
					<div class="absolute -top-2 -right-2 w-4 h-4">
						<span class="relative flex h-4 w-4">
							<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
							<span class="relative inline-flex rounded-full h-4 w-4 bg-indigo-500"></span>
						</span>
					</div>
				</div>
			</div>
		</div>
	</section>

	<!-- Clinical Guidelines Feature Highlight -->
	<section class="relative z-10 px-6 py-20 max-w-6xl mx-auto">
		<div class="card-dark relative overflow-hidden">
			<!-- Decorative gradient background -->
			<div class="absolute inset-0 bg-gradient-to-br from-teal-600/10 via-cyan-600/10 to-blue-600/10"></div>
			
			<div class="relative z-10 grid md:grid-cols-2 gap-8 items-center">
				<!-- Left: Visual representation -->
				<div class="relative order-2 md:order-1">
					<!-- Simulated guideline cards -->
					<div class="relative space-y-3">
						<!-- Guideline Card 1 -->
						<div class="bg-gradient-to-r from-teal-500/10 to-cyan-500/10 backdrop-blur-xl border border-teal-500/30 rounded-lg p-4 hover:border-teal-400/50 transition-all">
							<div class="flex items-center gap-2 mb-2">
								<div class="w-2 h-2 rounded-full bg-teal-400"></div>
								<span class="text-sm font-semibold text-teal-300">Pulmonary Nodule</span>
							</div>
							<div class="space-y-2 text-xs text-gray-300">
								<div class="flex items-start gap-2">
									<span class="text-purple-400 font-medium">Classification:</span>
									<span>Fleischner Society Criteria</span>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-blue-400 font-medium">Measurement:</span>
									<span>Average diameter, thin-slice CT</span>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-yellow-400 font-medium">DDx:</span>
									<span>Granuloma, adenocarcinoma, metastasis</span>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-orange-400 font-medium">Follow-up:</span>
									<span>CT chest at 3 months</span>
								</div>
							</div>
						</div>
						
						<!-- Guideline Card 2 -->
						<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-lg p-4 hover:border-white/20 transition-all">
							<div class="flex items-center gap-2 mb-2">
								<div class="w-2 h-2 rounded-full bg-cyan-400"></div>
								<span class="text-sm font-semibold text-cyan-300">Renal Cyst</span>
							</div>
							<div class="space-y-2 text-xs text-gray-400">
								<div class="flex items-start gap-2">
									<span class="text-purple-400 font-medium">Classification:</span>
									<span>Bosniak IIF</span>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-blue-400 font-medium">Imaging:</span>
									<span>Minimal enhancement, thin septa</span>
								</div>
							</div>
						</div>
						
						<!-- Reference indicator -->
						<div class="flex items-center gap-2 text-xs text-gray-500 pl-2">
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
							</svg>
							<span>3 medical references attached</span>
						</div>
					</div>
					
					<!-- Decorative element -->
					<div class="absolute -bottom-2 -left-2 w-4 h-4">
						<span class="relative flex h-4 w-4">
							<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"></span>
							<span class="relative inline-flex rounded-full h-4 w-4 bg-teal-500"></span>
						</span>
					</div>
				</div>
				
				<!-- Right: Content -->
				<div class="order-1 md:order-2">
					<div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-teal-500/10 border border-teal-500/20 mb-4">
						<svg class="w-4 h-4 text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
						</svg>
						<span class="text-xs font-medium text-teal-300">Evidence-Based</span>
					</div>
					
					<h2 class="text-3xl md:text-4xl font-bold text-white mb-4">
						Instant Clinical Guidelines & Evidence
					</h2>
					
					<p class="text-lg text-gray-300 mb-6 leading-relaxed">
						Every finding in your report gets comprehensive clinical context automatically. Access classification systems, measurement protocols, differential diagnoses, and follow-up recommendations—all sourced from current medical literature.
					</p>
					
					<div class="space-y-3">
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							</div>
							<div>
								<div class="text-white font-medium">Classification Systems</div>
								<div class="text-sm text-gray-400">BI-RADS, Fleischner, Bosniak, LI-RADS, and more—automatically referenced</div>
							</div>
						</div>
						
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							</div>
							<div>
								<div class="text-white font-medium">Standardized Measurement Protocols</div>
								<div class="text-sm text-gray-400">Learn proper measurement techniques and normal ranges for any finding</div>
							</div>
						</div>
						
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							</div>
							<div>
								<div class="text-white font-medium">Differential Diagnoses & Follow-up</div>
								<div class="text-sm text-gray-400">Comprehensive DDx with imaging features and follow-up recommendations</div>
							</div>
						</div>
						
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							</div>
							<div>
								<div class="text-white font-medium">Medical Literature References</div>
								<div class="text-sm text-gray-400">Every guideline includes citations and links to source material</div>
							</div>
						</div>
					</div>
				</div>
			</div>
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
		animation: fade-in 0.3s ease-out;
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
