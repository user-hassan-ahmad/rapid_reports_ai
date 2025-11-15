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
			icon: '⚡',
			title: 'Lightning Fast Generation',
			description: 'Generate professional radiology reports in seconds using advanced AI models',
			details: 'Our AI-powered system transforms your findings into comprehensive radiology reports instantly. Get accurate, professional reports that save you hours of work, powered by state-of-the-art artificial intelligence.'
		},
		{
			icon: '🎯',
			title: 'Custom Templates',
			description: 'Create and manage your own report templates with custom variables and instructions',
			details: 'Build your own library of report templates tailored to your workflow. Define custom variables, set master prompt instructions, and organise templates with tags. Full version history lets you experiment freely and restore previous versions anytime.'
		},
		{
			icon: '🤖',
			title: 'Intelligent Assistant',
			description: 'Your AI copilot pulls in contextual, accurate guideline information and helps refine reports through chat',
			details: 'Get intelligent assistance that automatically pulls in relevant clinical guidelines and contextual information. Chat with your reports to refine, enhance, and improve them. The assistant understands radiology terminology and helps ensure completeness and accuracy.'
		},
		{
			icon: '🎤',
			title: 'Real-time Dictation',
			description: 'Medical-grade transcription using Deepgram\'s Nova-3 Medical model',
			details: 'Speak your findings naturally and watch them transcribed in real-time. Powered by Deepgram\'s specialised Nova-3 Medical model, our dictation feature understands medical terminology and provides accurate transcriptions optimised for radiology workflows.'
		},
		{
			icon: '📊',
			title: 'Version History',
			description: 'Full version control for both templates and reports with restore capabilities',
			details: 'Never lose your work. Every template and report maintains a complete version history. Compare versions, see what changed, and restore any previous version with a single click. Track usage statistics and see which templates are most effective.'
		},
		{
			icon: '🔒',
			title: 'Secure & Private',
			description: 'Enterprise-grade security with encrypted storage and JWT authentication',
			details: 'Your data is protected with industry-standard encryption. All API keys are encrypted at rest, and we use JWT tokens for secure authentication. Built with privacy in mind, ensuring your radiology reports remain confidential and secure.'
		}
	];

	let stats = [
		{ value: '10x', label: 'Faster Report Generation' },
		{ value: '99%', label: 'Accuracy Rate' },
		{ value: '24/7', label: 'Available' }
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
			<h1 class="text-5xl md:text-7xl font-bold text-white mb-6 leading-tight">
				Your AI
				<span class="bg-gradient-to-r from-purple-400 via-blue-400 to-purple-400 bg-clip-text text-transparent animate-gradient">
					Radiology Reporting Copilot
				</span>
			</h1>
			<p class="text-xl md:text-2xl text-gray-300 mb-8 max-w-3xl mx-auto leading-relaxed">
				Transform your radiology workflow with AI-powered precision. Generate comprehensive reports, refine with intelligent guidance, and deliver with confidence.
			</p>
			<div class="flex flex-col sm:flex-row items-center justify-center gap-4">
				<a href="/register" class="btn-primary text-lg px-8 py-4 text-lg font-semibold">
					Start Free Trial →
				</a>
				<a href="/login" class="btn-secondary text-lg px-8 py-4">
					Sign In
				</a>
			</div>
		</div>

		<!-- Stats -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-16 max-w-3xl mx-auto">
			{#each stats as stat}
				<div class="card-dark text-center">
					<div class="text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-blue-400 mb-2">
						{stat.value}
					</div>
					<div class="text-gray-400">{stat.label}</div>
				</div>
			{/each}
		</div>
	</section>

	<!-- Features Section -->
	<section class="relative z-10 px-6 py-20 max-w-7xl mx-auto">
		<div class="text-center mb-16">
			<h2 class="text-4xl md:text-5xl font-bold text-white mb-4">
				Intelligent
				<span class="bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
					Reporting Companion
				</span>
			</h2>
			<p class="text-xl text-gray-400 max-w-2xl mx-auto">
				Everything you need to streamline your radiology reporting workflow
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
						<div class="text-4xl">{feature.icon}</div>
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
							<p class="text-gray-300 leading-relaxed">{feature.details}</p>
						</div>
					</div>
				</div>
			{/each}
		</div>
	</section>

	<!-- CTA Section -->
	<section class="relative z-10 px-6 py-20 max-w-4xl mx-auto text-center">
		<div class="card-dark relative overflow-hidden">
			<!-- Background gradient -->
			<div class="absolute inset-0 bg-gradient-to-r from-purple-600/20 to-blue-600/20"></div>
			<div class="relative z-10">
				<h2 class="text-4xl md:text-5xl font-bold text-white mb-6">
					Ready to Transform Your Workflow?
				</h2>
				<p class="text-xl text-gray-300 mb-8 max-w-2xl mx-auto">
					Join radiologists who are already using RadFlow to save time and improve accuracy.
				</p>
				<div class="flex flex-col sm:flex-row items-center justify-center gap-4">
					<a href="/register" class="btn-primary text-lg px-8 py-4 font-semibold">
						Get Started Free →
					</a>
					<a href="/login" class="btn-secondary text-lg px-8 py-4">
						Sign In to Your Account
					</a>
				</div>
			</div>
		</div>
	</section>

	<!-- Footer -->
	<footer class="relative z-10 px-6 py-12 border-t border-white/10">
		<div class="max-w-7xl mx-auto">
			<div class="text-center mb-8">
				<div class="flex items-center justify-center space-x-3 mb-4">
					<img src={logo} alt="RadFlow" class="h-12 w-auto" />
					<span class="text-lg font-semibold text-white">RadFlow</span>
				</div>
				<p class="text-gray-400 mb-4">
					AI-Powered Radiology Report Copilot
				</p>
				<div class="flex items-center justify-center space-x-6 text-sm text-gray-500">
					<a href="/login" class="hover:text-gray-300 transition-colors">Login</a>
					<a href="/register" class="hover:text-gray-300 transition-colors">Register</a>
				</div>
			</div>
			
			<!-- Legal Disclaimer -->
			<div class="mt-12 pt-8 border-t border-white/5">
				<div class="max-w-4xl mx-auto">
					<button
						onclick={() => disclaimerExpanded = !disclaimerExpanded}
						class="w-full flex items-center justify-between gap-4 mb-4 text-sm font-semibold text-white hover:text-purple-300 transition-colors"
					>
						<span>Legal Disclaimer</span>
						<svg 
							class="w-5 h-5 transition-transform duration-300 {disclaimerExpanded ? 'rotate-180' : ''}"
							fill="none" 
							stroke="currentColor" 
							viewBox="0 0 24 24"
						>
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
						</svg>
					</button>
					<div 
						class="overflow-hidden transition-all duration-500 ease-in-out"
						style="max-height: {disclaimerExpanded ? '2000px' : '0px'}; opacity: {disclaimerExpanded ? '1' : '0'};"
					>
						<div class="text-xs text-gray-400 leading-relaxed space-y-3">
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
			</div>
		</div>
	</footer>
</div>

<style>
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
</style>
