<script>
	import { onMount } from 'svelte';
	import { isAuthenticated } from '$lib/stores/auth';
	import logo from '$lib/assets/radflow-logo.png';
	
	let activeSection = 'quick-start';
	let expandedFaq = null;
	let expandedTemplateType = null;
	let mobileMenuOpen = false;
	let expandedTemplateSubsections = false;
	let lastActiveSubsection = null; // Track last active subsection for restoration
	
	const sections = [
		{ id: 'quick-start', title: 'Quick Start', icon: '🚀' },
		{ id: 'quick-report-generation', title: 'Quick Report Generation', icon: '⚡' },
		{ 
			id: 'template-report-generation', 
			title: 'Template Report Generation', 
			icon: '📋',
			subsections: [
				{ id: 'using-templates', title: 'Using Templates' },
				{ id: 'template-organization', title: 'Template Organization' },
				{ id: 'template-editor', title: 'Template Editor' },
				{ id: 'creating-templates', title: 'Creating Templates (Wizard)' },
				{ id: 'template-writing-guide', title: 'Template Writing Guide' },
				{ id: 'writing-style-optimizations', title: 'Writing Style Optimizations' }
			]
		},
		{ id: 'history', title: 'History', icon: '🕒' },
		{ id: 'enhancement', title: 'Enhancement', icon: '✨' },
		{ id: 'comparison', title: 'Interval Comparison', icon: '📊' },
		{ id: 'quality-control', title: 'Quality Control', icon: '🎯' },
		{ id: 'version-control', title: 'Version Control', icon: '🔄' },
		{ id: 'dictation', title: 'Dictation', icon: '🎤' },
		{ id: 'settings', title: 'Settings', icon: '⚙️' },
		{ id: 'faq', title: 'FAQ', icon: '❓' }
	];
	
	const faqs = [
		{
			q: "What's the difference between Auto Report and Templated Report?",
			a: "Auto Report is for quick, ad-hoc reporting—paste your raw findings (even unstructured notes) and AI instantly structures them into NHS-standard sections (COMPARISON, LIMITATIONS, FINDINGS, IMPRESSION) with proper medical language. No setup required. Templated Report is for consistent, repeatable reporting where you've configured specific formatting, writing styles, and section structures. Create a template once (via the 7-step wizard), then reuse it across similar cases for institutional consistency. Think of Auto Report as 'quick draft mode' and Templated Report as 'standardized production mode.'"
		},
		{
			q: "Which template type should I use?",
			a: "Choose based on how much control you need: (1) Normal Template—Best for most users. Paste any normal report as your template and AI adapts your natural language when pathology is present. No special syntax needed. (2) Guided Template—Same as Normal but you can add context comments (using // syntax) to guide AI on what to look for. Great for complex cases where you want specific assessment guidance. (3) Structured Fill-In—For maximum precision. Use placeholders for exact formatting control. AI fills in blanks but preserves your template structure exactly. Best for institutional standardization. (4) Systematic Checklist—Just list anatomical structures as bullet points and AI generates complete findings for each item. Perfect for ensuring nothing gets missed in complex examinations."
		},
		{
			q: "What does Enhancement do and when should I use it?",
			a: "After generating any report, three enhancement cards appear at the top. Click them to access: (1) Clinical Guidelines—AI searches medical literature for your findings and provides classification systems (BI-RADS, Fleischner, LI-RADS, etc.), measurement protocols, differential diagnoses, and follow-up recommendations with source references. Great for complex or unfamiliar findings. (2) Interval Comparison—Upload prior reports and AI identifies what's new, changed, or stable with automatic measurement tracking and growth rate calculations. Generates a revised report with properly formatted comparison statements. Essential for follow-up studies. (3) AI Chat—Ask questions about your report, request edits, or explore clinical implications. AI proposes surgical edits showing exactly what will change. Use it to refine language, add differentials, or clarify findings."
		},
		{
			q: "How does Interval Comparison work in practice?",
			a: "Real workflow example: You generate a chest CT report showing a lung nodule. Click the Comparison enhancement card, then 'Add Prior Report.' Paste the prior CT report text, enter the study date (e.g., 15/08/2024), and scan type. Click 'Analyze Interval Changes.' AI creates a detailed analysis with three color-coded sections: (Red) New Findings—pathology not present before with urgency flags if concerning. (Yellow) Changed Findings—prior measurements vs current with absolute change, percentage growth, and time interval calculated automatically. (Green) Stable Findings—what hasn't changed. You then get a 'Report Modifications' section showing side-by-side original vs revised text for each change. Click 'Preview Full Revised Report' to see the complete updated report, or 'Apply Comparison Report' to create a new version with all interval changes properly documented."
		},
		{
			q: "What are unfilled placeholders and how do I fix them?",
			a: "Only applies to Structured Fill-In templates. When AI can't extract a specific value from your findings, it leaves the placeholder unfilled and highlights it in color: Green highlights = Named variables (e.g., LVEF={LVEF}% stayed unfilled). Yellow highlights = Generic measurements (xxx stayed as xxx). Purple highlights = Alternatives where AI couldn't choose (e.g., [normal/dilated] stayed bracketed). Orange highlights = Blank sections with no content. To fill them: hover over any colored highlight and a popup appears. You can either type the value manually or click 'Fill with AI'—AI analyzes the surrounding context and proposes a value. Review and accept to remove the highlight. This quality control system ensures no critical information gets missed in structured reports."
		},
		{
			q: "Can I undo changes and compare versions?",
			a: "Yes, complete version control. Click the version icon (top-right of any report) to see full history. Every change creates a new version automatically: when you manually edit content, apply AI chat suggestions, or apply interval comparison changes. Each version shows a tag badge (blue=Manual Edit, green=Chat Edit, amber=Comparison Edit) so you know how it was created. To compare versions: toggle 'Track Changes' and select two versions from the dropdown. The diff viewer highlights additions in green and deletions in red, making it easy to see exactly what changed. To restore: click 'Restore' on any old version and it creates a new version with that content—nothing is ever permanently deleted. This is critical for reviewing report evolution over time or recovering from unwanted changes."
		},
		{
			q: "How do I set up dictation?",
			a: "Dictation requires your own Deepgram API key (medical-grade transcription). Setup: (1) Go to console.deepgram.com and create a free account. (2) Generate an API key from their console. (3) In RadFlow, click Settings in the sidebar. (4) Scroll to 'API Keys' section and paste your Deepgram key. (5) Click Save. Once configured, you'll see microphone icons (🎤) throughout the app wherever text input is available (Clinical History, Findings, etc.). Two modes available in Settings: Streaming mode (default)—text appears in real-time as you speak, great for live dictation. Batch mode—record your complete finding, then click stop to generate text, better for reviewing before insertion. The medical vocabulary model understands complex anatomical terms and abbreviations automatically."
		},
		{
			q: "Is my data secure and private?",
			a: "Yes, security is built-in at every level. Your passwords are securely hashed (not stored as plain text) and API keys are encrypted before storage—even the database administrator can't read them. All data stays in secure databases with no sharing to third parties. Report content is your private medical data and is never used to train AI models or shared externally. The app is currently in beta and completely free to use—no payment information required, so there's no financial data stored. Your reports, templates, and settings are accessible only to your account. We take data protection seriously and follow medical data handling best practices."
		},
		{
			q: "Can I use this for production clinical reporting?",
			a: "RadFlow is currently in BETA testing. While we've built robust features with medical-grade AI models and follow NHS reporting standards, the app is still under active development. Use it as a powerful assistant for drafting reports and exploring clinical decision support, but always review all AI-generated content carefully before clinical use. We recommend treating it as a 'smart co-pilot' that accelerates your workflow but doesn't replace clinical judgment. All generated reports should be reviewed and signed off by qualified clinicians. We're gathering feedback to improve accuracy, reliability, and clinical safety before any production release. If you encounter issues or have suggestions, your feedback helps us build a better product."
		},
		{
			q: "What happens to my templates if I create them with the wizard vs the editor?",
			a: "They're identical—same template, just different interfaces for different stages. Always use the 7-step wizard first to create new templates. It walks you through every configuration option with explanations and examples at each step, making it perfect for first-time template creation. Once a template exists, always use the 3-tab editor (Quick Edit, Findings, Impression) to modify it. The editor contains all the same settings but organized in tabs for faster access when you already know what you want to change. Both save to the same template library, so your workflow is: wizard to create, editor to modify."
		}
	];
	
	function scrollToSection(sectionId) {
		mobileMenuOpen = false; // Close mobile menu when navigating
		
		const templateSection = sections.find(s => s.id === 'template-report-generation');
		const isTemplateSection = sectionId === 'template-report-generation';
		const isTemplateSubsection = templateSection?.subsections?.some(s => s.id === sectionId);
		
		// Clear saved subsection if navigating away from template section entirely
		if (!isTemplateSection && !isTemplateSubsection) {
			lastActiveSubsection = null; // Clear saved subsection when navigating to a different section
		}
		
		// Handle Template Report Generation section specially - toggle expansion on click
		if (isTemplateSection) {
			if (templateSection?.subsections) {
				// Check if parent section or any subsection is currently active
				const isParentActive = activeSection === 'template-report-generation';
				const isSubsectionActive = templateSection.subsections.some(s => s.id === activeSection);
				const isCurrentlyActive = isParentActive || isSubsectionActive;
				
				// If already active and expanded, collapse. Otherwise expand and navigate
				if (isCurrentlyActive && expandedTemplateSubsections) {
					// Save active subsection before collapsing if one is active
					if (isSubsectionActive) {
						lastActiveSubsection = activeSection;
					}
					expandedTemplateSubsections = false;
					activeSection = sectionId; // Keep section active
					lastActiveSubsection = null; // Clear saved subsection when explicitly collapsing via parent click
					return; // Don't scroll if just collapsing
				} else {
					expandedTemplateSubsections = true;
					// Only restore saved subsection if it still exists and we're coming back to template section
					// (not if we're already on a template subsection)
					if (lastActiveSubsection && !isSubsectionActive) {
						const subsectionExists = templateSection.subsections.some(s => s.id === lastActiveSubsection);
						if (subsectionExists) {
							activeSection = lastActiveSubsection;
							const element = document.getElementById(lastActiveSubsection);
							if (element) {
								setTimeout(() => {
									element.scrollIntoView({ behavior: 'smooth', block: 'start' });
								}, 100);
								return;
							}
						}
					}
					activeSection = sectionId;
					// Scroll to section
					const element = document.getElementById(sectionId);
					if (element) {
						element.scrollIntoView({ behavior: 'smooth', block: 'start' });
					}
					return;
				}
			}
		} else if (isTemplateSubsection) {
			// Auto-expand Template Report Generation section if clicking a subsection
			expandedTemplateSubsections = true;
			lastActiveSubsection = sectionId; // Track active subsection
		}
		
		activeSection = sectionId;
		
		const element = document.getElementById(sectionId);
		if (element) {
			element.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}
	
	function formatFaqAnswer(answer) {
		let html = '';
		
		// Check if answer contains numbered lists
		const hasNumberedLists = /\(\d+\)/.test(answer);
		
		if (hasNumberedLists) {
			// Split by numbered list pattern: (1), (2), etc. - handle both em-dash and regular dash
			const parts = [];
			
			// Find all numbered items - match (1) Title—Description or (1) Title-Description
			const itemMatches = [...answer.matchAll(/\((\d+)\)\s+([^—\-]+)(?:—|-\s*)/g)];
			
			if (itemMatches.length > 0) {
				// Add intro text before first item
				const firstMatch = itemMatches[0];
				if (firstMatch.index > 0) {
					const introText = answer.substring(0, firstMatch.index).trim();
					if (introText) {
						parts.push({ type: 'text', content: introText });
					}
				}
				
				// Process each numbered item
				itemMatches.forEach((match, idx) => {
					const itemStart = match.index + match[0].length;
					const itemEnd = idx < itemMatches.length - 1 
						? itemMatches[idx + 1].index 
						: answer.length;
					
					const itemTitle = match[2].trim();
					let itemDescription = answer.substring(itemStart, itemEnd).trim();
					
					// Format description to break into paragraphs if multiple sentences
					itemDescription = formatDescription(itemDescription);
					
					parts.push({ 
						type: 'numbered-item', 
						number: match[1], 
						title: itemTitle, 
						description: itemDescription 
					});
				});
			}
			
			// Build HTML
			let inList = false;
			parts.forEach((part) => {
				if (part.type === 'numbered-item' && 'title' in part && 'description' in part) {
					if (!inList) {
						html += '<ol class="list-decimal space-y-3 my-4 ml-4">';
						inList = true;
					}
					const highlightedTitle = highlightTerms(String(part.title));
					// Description is already formatted, just highlight terms
					const description = String(part.description);
					const highlightedDesc = description.includes('<') 
						? description 
						: highlightTerms(description);
					html += `<li class="pl-1"><span class="font-semibold text-white">${highlightedTitle}—</span> ${highlightedDesc}</li>`;
				} else if (part.type === 'text' && 'content' in part) {
					if (inList) {
						html += '</ol>';
						inList = false;
					}
					const highlighted = highlightTerms(String(part.content));
					html += formatParagraphs(highlighted);
				}
			});
			
			if (inList) {
				html += '</ol>';
			}
			
		} else {
			// For non-numbered answers, split into paragraphs
			let processed = highlightTerms(answer);
			html = formatParagraphs(processed);
		}
		
		return html;
	}
	
	function formatDescription(description) {
		// Break long descriptions into paragraphs for better readability
		// Look for sentence patterns that indicate paragraph breaks
		// Split on periods followed by capital letters (but not abbreviations)
		const sentences = description.split(/(?<=[.!?])\s+(?=[A-Z][a-z])/);
		
		if (sentences.length > 1) {
			// Multiple sentences - format as paragraphs
			return sentences.map(s => s.trim()).filter(s => s.length > 0)
				.map(s => `<span class="block mb-2">${s}</span>`).join('');
		}
		
		return description;
	}
	
	function formatParagraphs(text) {
		// Split text into logical paragraphs
		// Pattern 1: Period followed by capital letter and substantial text (new paragraph)
		// Pattern 2: Colon followed by space and capital (list-like structure)
		// Pattern 3: Double newlines or explicit breaks
		
		// First, handle explicit breaks
		if (text.includes('\n\n')) {
			return text.split(/\n\n+/).map(p => `<p class="mb-3">${p.trim()}</p>`).join('');
		}
		
		// Split by sentence patterns that suggest paragraph breaks
		// Look for: . [space] [Capital] [substantial text] pattern
		const paragraphRegex = /(?<=[.!?])\s+(?=[A-Z][a-z][^.!?]{30,})/g;
		const paragraphs = text.split(paragraphRegex);
		
		if (paragraphs.length > 1) {
			return paragraphs.map(p => p.trim()).filter(p => p.length > 15)
				.map(p => `<p class="mb-3">${p}</p>`).join('');
		}
		
		// Try splitting by colons (list-like structures)
		if (text.includes(':') && text.split(':').length > 2) {
			const colonParts = text.split(/(?<=:)\s+(?=[A-Z])/);
			if (colonParts.length > 1) {
				return colonParts.map(p => p.trim()).filter(p => p.length > 10)
					.map(p => `<p class="mb-3">${p}</p>`).join('');
			}
		}
		
		// Single paragraph
		return `<p>${text}</p>`;
	}
	
	function highlightTerms(text) {
		// Don't process if text already contains HTML tags (already processed)
		if (typeof text !== 'string' || text.includes('<code') || text.includes('<a')) {
			return text;
		}
		
		let result = text;
		
		// Simple, minimal highlighting - only for truly technical elements
		// 1. Code patterns: {VAR}, [options], `code`, // comments
		result = result.replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, '<code>{$1}</code>');
		result = result.replace(/\[([^\]]+)\]/g, '<code>[$1]</code>');
		result = result.replace(/`([^`]+)`/g, '<code>$1</code>');
		result = result.replace(/(\/\/[^\s\)]+)/g, '<code>$1</code>');
		
		// 2. URLs - make them actual links
		result = result.replace(/(https?:\/\/[^\s]+|console\.deepgram\.com)/gi, (match) => {
			const url = match.startsWith('http') ? match : `https://${match}`;
			return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-blue-400 hover:underline">${match}</a>`;
		});
		
		// 3. Section headers in ALL CAPS (only specific ones)
		const sectionHeaders = ['COMPARISON', 'LIMITATIONS', 'FINDINGS', 'IMPRESSION'];
		sectionHeaders.forEach(header => {
			const regex = new RegExp(`\\b(${header})\\b`, 'g');
			result = result.replace(regex, '<strong>$1</strong>');
		});
		
		return result;
	}
	
	function toggleTemplateSubsections(event) {
		event?.stopPropagation();
		const templateSection = sections.find(s => s.id === 'template-report-generation');
		const isParentActive = activeSection === 'template-report-generation';
		const isSubsectionActive = templateSection?.subsections?.some(s => s.id === activeSection);
		const isInTemplateContext = isParentActive || isSubsectionActive;
		
		if (expandedTemplateSubsections) {
			// Collapsing: save the active subsection if one is active, then reset to parent
			if (isSubsectionActive) {
				lastActiveSubsection = activeSection;
				activeSection = 'template-report-generation';
			}
			expandedTemplateSubsections = false;
		} else {
			// Expanding: only restore saved subsection if we're still in template context
			// (i.e., we collapsed from within template section, not after navigating away)
			expandedTemplateSubsections = true;
			if (lastActiveSubsection && isInTemplateContext) {
				// Check if the subsection still exists and restore it (highlight it)
				const subsectionExists = templateSection?.subsections?.some(s => s.id === lastActiveSubsection);
				if (subsectionExists) {
					activeSection = lastActiveSubsection;
					// Let IntersectionObserver handle scrolling naturally if needed
				} else {
					// Subsection no longer exists, clear it
					lastActiveSubsection = null;
				}
			} else if (!isInTemplateContext) {
				// We're expanding from outside template context, clear any saved subsection
				lastActiveSubsection = null;
			}
		}
	}
	
	function toggleMobileMenu() {
		mobileMenuOpen = !mobileMenuOpen;
		// Prevent body scroll when menu is open
		if (typeof document !== 'undefined') {
			if (mobileMenuOpen) {
				document.body.style.overflow = 'hidden';
			} else {
				document.body.style.overflow = '';
			}
		}
	}
	
	onMount(() => {
		// Update active section on scroll
		const observer = new IntersectionObserver(
			(entries) => {
				entries.forEach((entry) => {
					if (entry.isIntersecting) {
						activeSection = entry.target.id;
						
						// Auto-expand Template Report Generation section if a subsection becomes active
						const templateSection = sections.find(s => s.id === 'template-report-generation');
						if (templateSection?.subsections?.some(s => s.id === entry.target.id)) {
							expandedTemplateSubsections = true;
						}
					}
				});
			},
			{ threshold: 0.3 }
		);
		
		sections.forEach((section) => {
			const element = document.getElementById(section.id);
			if (element) observer.observe(element);
			
			// Also observe subsections if they exist
			if (section.subsections) {
				section.subsections.forEach((subsection) => {
					const subElement = document.getElementById(subsection.id);
					if (subElement) observer.observe(subElement);
				});
			}
		});
		
		// Cleanup
		return () => {
			observer.disconnect();
			// Restore body scroll on unmount
			if (typeof document !== 'undefined') {
				document.body.style.overflow = '';
			}
		};
	});
</script>

<svelte:head>
	<title>Documentation - RadFlow</title>
</svelte:head>

<div class="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900">
	<!-- Header -->
	<header class="sticky top-0 z-50 bg-black/80 backdrop-blur-lg border-b border-white/10">
		<div class="max-w-7xl mx-auto px-4 sm:px-6 py-3 sm:py-4 flex items-center justify-between">
			<a href={$isAuthenticated ? '/' : '/home'} class="flex items-center gap-2 sm:gap-3">
				<img src={logo} alt="RadFlow" class="h-8 sm:h-10 w-auto" />
				<span class="text-lg sm:text-xl font-bold text-white">RadFlow Docs</span>
			</a>
			<div class="flex items-center gap-2 sm:gap-4">
				{#if $isAuthenticated}
					<a href="/" class="px-3 sm:px-4 py-1.5 sm:py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-lg text-xs sm:text-sm font-medium hover:from-purple-500 hover:to-blue-500 transition-all">
						← Back to App
					</a>
				{:else}
					<a href="/login" class="text-gray-300 hover:text-white transition-colors text-xs sm:text-sm">Sign In</a>
					<a href="/register" class="px-3 sm:px-4 py-1.5 sm:py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-lg text-xs sm:text-sm font-medium hover:from-purple-500 hover:to-blue-500 transition-all">
						Try It Out
					</a>
				{/if}
			</div>
		</div>
	</header>

	<!-- Mobile Menu Button (Top-Left) -->
	<button
		onclick={toggleMobileMenu}
		class="lg:hidden fixed top-20 left-4 z-50 w-12 h-12 bg-white/10 backdrop-blur-xl border border-white/20 text-white rounded-lg shadow-lg flex items-center justify-center hover:bg-white/20 transition-all"
		aria-label="Toggle navigation menu"
	>
		<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			{#if mobileMenuOpen}
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
			{:else}
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
			{/if}
		</svg>
	</button>

	<!-- Mobile Navigation Overlay -->
	{#if mobileMenuOpen}
		<div 
			class="lg:hidden fixed inset-0 bg-black/80 backdrop-blur-sm z-40 animate-fade-in"
			onclick={toggleMobileMenu}
		></div>
		<div class="lg:hidden fixed inset-y-0 left-0 w-64 bg-gray-900/95 backdrop-blur-xl border-r border-white/10 z-50 overflow-y-auto shadow-2xl animate-slide-in-left">
			<div class="p-6">
				<div class="flex items-center justify-between mb-6">
					<h3 class="text-lg font-bold text-white">Contents</h3>
					<button
						onclick={toggleMobileMenu}
						class="text-gray-400 hover:text-white transition-colors"
						aria-label="Close menu"
					>
						<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>
				<ul class="space-y-1">
					{#each sections as section}
						<li>
							<div class="flex items-start gap-2 w-full">
								<button
									onclick={() => scrollToSection(section.id)}
									class="flex-1 text-left px-4 py-3 rounded-lg transition-all {activeSection === section.id || (section.subsections && section.subsections.some(s => s.id === activeSection)) ? 'bg-purple-600 text-white' : 'text-gray-300 hover:bg-white/5 hover:text-white'}"
								>
									<div class="flex items-start gap-3">
										<span class="flex-shrink-0 text-lg">{section.icon}</span>
										<span class="text-sm font-medium leading-tight break-words flex-1 min-w-0">{section.title}</span>
									</div>
								</button>
								{#if section.subsections}
									<button
										onclick={(e) => toggleTemplateSubsections(e)}
										class="flex-shrink-0 px-2 py-3 text-gray-400 hover:text-white transition-transform {expandedTemplateSubsections ? 'rotate-90' : ''}"
										aria-label={expandedTemplateSubsections ? 'Collapse subsections' : 'Expand subsections'}
									>
										<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
										</svg>
									</button>
								{/if}
							</div>
							{#if section.subsections && (expandedTemplateSubsections || section.subsections.some(s => s.id === activeSection))}
								<ul class="ml-6 mt-1 space-y-0.5 animate-fade-in">
									{#each section.subsections as subsection}
										<li>
											<button
												onclick={() => { scrollToSection(subsection.id); mobileMenuOpen = false; }}
												class="w-full text-left px-4 py-2 rounded-lg transition-all text-xs {activeSection === subsection.id ? 'bg-purple-500/30 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'}"
											>
												<span class="ml-1">• {subsection.title}</span>
											</button>
										</li>
									{/each}
								</ul>
							{/if}
						</li>
					{/each}
				</ul>
			</div>
		</div>
	{/if}

	<div class="max-w-7xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
		<div class="flex gap-8">
			<!-- Desktop Sidebar Navigation -->
			<aside class="hidden lg:block w-64 flex-shrink-0">
				<div class="sticky top-24">
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-4">
						<h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Contents</h3>
						<ul class="space-y-1">
							{#each sections as section}
								<li>
									<div class="flex items-start gap-1 w-full">
										<button
											onclick={() => scrollToSection(section.id)}
											class="flex-1 text-left px-3 py-2 rounded-lg transition-all {activeSection === section.id || (section.subsections && section.subsections.some(s => s.id === activeSection)) ? 'bg-purple-600 text-white' : 'text-gray-300 hover:bg-white/5 hover:text-white'}"
										>
											<div class="flex items-start gap-2">
												<span class="flex-shrink-0 mt-0.5">{section.icon}</span>
												<span class="text-sm leading-tight break-words flex-1 min-w-0">{section.title}</span>
											</div>
										</button>
										{#if section.subsections}
											<button
												onclick={(e) => toggleTemplateSubsections(e)}
												class="flex-shrink-0 px-1.5 py-2 text-gray-400 hover:text-white transition-transform {expandedTemplateSubsections ? 'rotate-90' : ''}"
												aria-label={expandedTemplateSubsections ? 'Collapse subsections' : 'Expand subsections'}
											>
												<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
												</svg>
											</button>
										{/if}
									</div>
									{#if section.subsections && (expandedTemplateSubsections || section.subsections.some(s => s.id === activeSection))}
										<ul class="ml-4 mt-1 space-y-0.5 animate-fade-in">
											{#each section.subsections as subsection}
												<li>
													<button
														onclick={() => scrollToSection(subsection.id)}
														class="w-full text-left px-3 py-1.5 rounded-lg transition-all text-xs {activeSection === subsection.id ? 'bg-purple-500/30 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'}"
													>
														<span class="ml-1">• {subsection.title}</span>
													</button>
												</li>
											{/each}
										</ul>
									{/if}
								</li>
							{/each}
						</ul>
					</div>
				</div>
			</aside>

			<!-- Main Content -->
			<main class="flex-1 min-w-0 space-y-12 sm:space-y-16">
				<!-- Quick Start -->
				<section id="quick-start" class="scroll-mt-24">
					<div class="bg-gradient-to-r from-purple-600/20 to-blue-600/20 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 sm:p-8">
						<h1 class="text-3xl sm:text-4xl font-bold text-white mb-4">🚀 Quick Start Guide</h1>
						<p class="text-lg sm:text-xl text-gray-300 mb-6 sm:mb-8">Get started with RadFlow in 3 easy steps</p>
						
						<div class="grid sm:grid-cols-2 md:grid-cols-3 gap-4 sm:gap-6">
							<div class="bg-black/30 rounded-lg p-5 sm:p-6 border border-white/10">
								<div class="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-2xl font-bold text-white mb-4">1</div>
								<h3 class="text-lg font-bold text-white mb-2">Create Account</h3>
								<p class="text-sm text-gray-400">Sign up with your email, verify your account via email link, and log in. No payment required during beta.</p>
							</div>
							
							<div class="bg-black/30 rounded-lg p-6 border border-white/10">
								<div class="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-2xl font-bold text-white mb-4">2</div>
								<h3 class="text-lg font-bold text-white mb-2">Generate Report</h3>
								<p class="text-sm text-gray-400">Use Auto Report for instant generation from raw findings, or create custom templates for consistent formatting.</p>
							</div>
							
							<div class="bg-black/30 rounded-lg p-6 border border-white/10">
								<div class="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-2xl font-bold text-white mb-4">3</div>
								<h3 class="text-lg font-bold text-white mb-2">Enhance & Refine</h3>
								<p class="text-sm text-gray-400">Click enhancement cards that appear above your report to access guidelines, comparison, and chat features.</p>
							</div>
						</div>
					</div>
				</section>

				<!-- Quick Report Generation -->
				<section id="quick-report-generation" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">⚡ Quick Report Generation</h2>
					
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-5 sm:p-6 md:p-8 mb-6">
						<h3 class="text-lg sm:text-xl font-bold text-white mb-4">Auto Report (Instant Generation)</h3>
						<p class="text-gray-300 mb-4 text-sm sm:text-base">Transform raw, unstructured findings into structured NHS-standard reports instantly—no template required. Perfect for quick, ad-hoc reporting.</p>
						
						<div class="bg-black/30 rounded-lg p-6 border border-purple-500/30 mb-4">
							<h4 class="text-white font-semibold mb-3">How to Use:</h4>
							<ol class="space-y-2 text-gray-300">
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">1.</span>
									<span>Stay on <strong>Auto Report</strong> tab (default tab when you log in)</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">2.</span>
									<span>Fill in three fields:</span>
								</li>
								<div class="ml-6 space-y-2 text-sm">
									<div class="bg-blue-500/10 p-3 rounded border border-blue-500/30">
										<strong class="text-blue-300">Clinical History:</strong> <span class="text-gray-400">Patient background, indication for scan</span>
									</div>
									<div class="bg-blue-500/10 p-3 rounded border border-blue-500/30">
										<strong class="text-blue-300">Scan Type:</strong> <span class="text-gray-400">Imaging modality and technical details</span>
									</div>
									<div class="bg-blue-500/10 p-3 rounded border border-blue-500/30">
										<strong class="text-blue-300">Findings:</strong> <span class="text-gray-400">Raw, unstructured observations (can use 🎤 dictation)</span>
									</div>
								</div>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">3.</span>
									<span>Click <strong>Generate Report</strong></span>
								</li>
							</ol>
							<div class="mt-4 p-3 bg-green-500/10 border border-green-500/30 rounded text-sm text-green-300">
								<strong>Result:</strong> AI structures your raw findings into proper sections (COMPARISON, LIMITATIONS, FINDINGS, IMPRESSION) with appropriate medical language and formatting.
							</div>
						</div>
						
						<div class="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
							<p class="text-sm text-yellow-300"><strong>Example Input:</strong> "4cm spiculated mass RUL, right paratracheal nodes 2cm, small left effusion"</p>
							<p class="text-xs text-yellow-400 mt-2">→ AI transforms into structured sections with proper medical prose</p>
						</div>
					</div>
					
					<div class="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 mt-6">
						<p class="text-sm text-blue-300"><strong>💡 When to Use Auto Report:</strong> Perfect for quick, one-off reports where you need instant structuring without template setup. For consistent, repeatable reporting with specific formatting requirements, see <a href="#template-report-generation" class="text-purple-300 hover:text-purple-200 underline">Template Report Generation</a>.</p>
					</div>
				</section>

				<!-- Template Report Generation -->
				<section id="template-report-generation" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">📋 Template Report Generation</h2>
					
					<!-- Using Templates -->
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-5 sm:p-6 md:p-8 mb-6">
						<h3 id="using-templates" class="text-lg sm:text-xl font-bold text-white mb-4 scroll-mt-24">Using Templates to Generate Reports</h3>
						<p class="text-gray-300 mb-4 text-sm sm:text-base">Generate reports using your custom templates for consistent formatting and style. Everything happens on one page.</p>
						
						<div class="bg-black/30 rounded-lg p-6 border border-purple-500/30 mb-4">
							<h4 class="text-white font-semibold mb-3">To Generate a Report:</h4>
							<ol class="space-y-3 text-gray-300 text-sm">
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">1.</span>
									<span>Sidebar → Click <strong>"Generate Custom Report"</strong></span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">2.</span>
									<span>Browse your templates (grid or kanban view), use search/filters as needed</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">3.</span>
									<div>
										<strong class="text-green-400">Click a template card</strong>
										<p class="text-xs text-gray-400 mt-1">→ Card highlights, input fields appear below the template cards</p>
									</div>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">4.</span>
									<span>Fill in the input fields (Clinical History, Findings, any custom sections from your template)</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">5.</span>
									<span>Click <strong>Generate Report</strong> → Report appears in viewer below</span>
								</li>
							</ol>
						</div>
						
						<div class="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-blue-300">
							<strong>No templates yet?</strong> Scroll down to learn about <a href="#creating-templates" class="text-purple-300 hover:text-purple-200 underline">Creating Templates</a> with the 7-step wizard.
						</div>
					</div>
					
					<!-- Template Organization -->
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8 mb-6">
						<h3 id="template-organization" class="text-xl font-bold text-white mb-4 scroll-mt-24">Template Organization</h3>
						<p class="text-gray-300 mb-6">Everything in one place: Sidebar → <strong>"Generate Custom Report"</strong> tab shows template selection, creation, and management all on one page</p>
						
						<div class="bg-black/30 rounded-lg p-6 border border-purple-500/30 mb-6">
							<h4 class="text-white font-semibold mb-3">Page Structure:</h4>
							<ol class="space-y-3 text-sm text-gray-300">
								<li class="flex items-start gap-2">
									<span class="text-purple-400 font-bold">1.</span>
									<div>
										<strong class="text-white">Header:</strong> "Generate Custom Report" title + "+ Create Template" button
									</div>
								</li>
								<li class="flex items-start gap-2">
									<span class="text-purple-400 font-bold">2.</span>
									<div>
										<strong class="text-white">Filters/Search:</strong> Search bar, tag filters, view mode toggle (Grid/Kanban), sort options
									</div>
								</li>
								<li class="flex items-start gap-2">
									<span class="text-purple-400 font-bold">3.</span>
									<div>
										<strong class="text-white">Template Cards:</strong> All your templates displayed as clickable cards
										<ul class="mt-2 ml-4 space-y-1 text-xs text-gray-400">
											<li>• <strong class="text-green-400">Click card</strong> → Input fields appear below for report generation</li>
											<li>• <strong class="text-blue-400">Hover + Edit button</strong> → Opens template editor interface</li>
											<li>• Other actions: Duplicate, Pin/Unpin, Delete</li>
										</ul>
									</div>
								</li>
								<li class="flex items-start gap-2">
									<span class="text-purple-400 font-bold">4.</span>
									<div>
										<strong class="text-white">Report Generation Area:</strong> Appears when template selected (Clinical History, Findings, custom fields + Generate button)
									</div>
								</li>
							</ol>
						</div>
						
						<div class="grid sm:grid-cols-2 gap-4 sm:gap-6">
							<div class="bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-lg p-5 sm:p-6 border border-purple-500/30">
								<h4 class="text-white font-semibold mb-3">🏷️ Tag System</h4>
								<ul class="space-y-2 text-sm text-gray-300">
									<li>• Organize templates with custom tags (e.g., "CT", "MRI", "Chest", "Urgent")</li>
									<li>• Click tags to filter templates</li>
									<li>• Click "Edit Tags" to rename or delete tags globally</li>
									<li>• Customize tag colors for visual organization</li>
									<li>• Tag counter shows usage (e.g., "CT (5)" means 5 templates)</li>
								</ul>
							</div>
							
							<div class="bg-gradient-to-r from-green-500/10 to-emerald-500/10 rounded-lg p-6 border border-green-500/30">
								<h4 class="text-white font-semibold mb-3">📊 View Modes</h4>
								<ul class="space-y-2 text-sm text-gray-300">
									<li>• <strong class="text-white">Grid View:</strong> Cards in responsive grid, pinned templates first</li>
									<li>• <strong class="text-white">Kanban View:</strong> Organized columns (by default or by tags)</li>
									<li>• Each card shows: name, description, tags, usage count</li>
									<li>• Search by name, description, or tags</li>
									<li>• Actions: Edit, Duplicate, Pin/Unpin, Delete</li>
								</ul>
							</div>
						</div>
					</div>
					
					<!-- Template Editor -->
					<div class="bg-gradient-to-r from-indigo-600/10 to-purple-600/10 backdrop-blur-xl border border-indigo-500/30 rounded-xl p-8 mb-6">
						<h3 id="template-editor" class="text-xl font-bold text-white mb-4 scroll-mt-24">✏️ Template Editor Interface</h3>
						<p class="text-gray-300 mb-6">Edit existing templates through the same 3-tab structure as the wizard (just condensed into tabs instead of steps)</p>
						
						<div class="bg-black/30 rounded-lg p-6 border border-white/10">
							<h4 class="text-white font-semibold mb-4">Three Tabs (Same as Wizard Steps):</h4>
							
							<div class="space-y-4">
								<div class="flex items-start gap-4">
									<div class="w-12 h-12 rounded-lg bg-blue-500/20 flex items-center justify-center flex-shrink-0">
										<span class="text-blue-300 font-bold text-lg">1</span>
									</div>
									<div class="flex-1">
										<h5 class="text-white font-semibold mb-2">Quick Edit Tab</h5>
										<p class="text-sm text-gray-400 mb-2">Basic info and structure configuration:</p>
										<ul class="text-xs text-gray-500 space-y-1 ml-4">
											<li>• Name, description, tags, pinning</li>
											<li>• Scan type, contrast, protocol details</li>
											<li>• Section configuration (which sections to include, order, input fields)</li>
											<li>• Global custom instructions</li>
										</ul>
										<p class="text-xs text-purple-400 mt-2"><strong>Wizard equivalent:</strong> Steps 1-3 (Scan Info, Section Builder)</p>
									</div>
								</div>
								
								<div class="flex items-start gap-4">
									<div class="w-12 h-12 rounded-lg bg-green-500/20 flex items-center justify-center flex-shrink-0">
										<span class="text-green-300 font-bold text-lg">2</span>
									</div>
									<div class="flex-1">
										<h5 class="text-white font-semibold mb-2">Findings Tab</h5>
										<p class="text-sm text-gray-400 mb-2">Content style selection and writing configuration:</p>
										<ul class="text-xs text-gray-500 space-y-1 ml-4">
											<li>• Choose content style (Normal/Guided/Structured/Checklist)</li>
											<li>• Write/edit template content for selected style</li>
											<li>• Configure writing style optimizations (all the granular controls)</li>
											<li>• Section-specific instructions</li>
										</ul>
										<p class="text-xs text-purple-400 mt-2"><strong>Wizard equivalent:</strong> Step 4 (Findings Setup)</p>
									</div>
								</div>
								
								<div class="flex items-start gap-4">
									<div class="w-12 h-12 rounded-lg bg-orange-500/20 flex items-center justify-center flex-shrink-0">
										<span class="text-orange-300 font-bold text-lg">3</span>
									</div>
									<div class="flex-1">
										<h5 class="text-white font-semibold mb-2">Impression Tab</h5>
										<p class="text-sm text-gray-400 mb-2">Impression generation configuration:</p>
										<ul class="text-xs text-gray-500 space-y-1 ml-4">
											<li>• Display name (rename "IMPRESSION" if needed)</li>
											<li>• Verbosity (Brief/Prose), format (prose/bullets/numbered)</li>
											<li>• Differential diagnosis style, recommendations, clinical correlation</li>
											<li>• Section-specific instructions</li>
										</ul>
										<p class="text-xs text-purple-400 mt-2"><strong>Wizard equivalent:</strong> Step 5 (Impression Setup)</p>
									</div>
								</div>
							</div>
						</div>
						
						<div class="mt-4 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg text-sm text-blue-300">
							<strong>Key Difference from Wizard:</strong> Editor shows all configuration in tabs (faster navigation), while wizard guides step-by-step. Same settings, different interface.
						</div>
					</div>
					
					<!-- Template Wizard -->
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8 mb-6">
						<h3 id="creating-templates" class="text-xl font-bold text-white mb-4 scroll-mt-24">Creating Templates: Template Wizard (7-Step Process)</h3>
						<p class="text-gray-300 mb-6">Build custom templates with guided step-by-step wizard—no technical knowledge required.</p>
						
						<div class="space-y-3">
							<div class="bg-black/30 rounded-lg p-4 border border-white/10">
								<div class="flex items-start gap-4">
									<div class="w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-bold flex-shrink-0">1</div>
									<div>
										<h4 class="text-white font-semibold mb-1">Scan Information</h4>
										<p class="text-sm text-gray-400">Scan type, contrast details (no contrast/with IV contrast/other), contrast phases, protocol details</p>
									</div>
								</div>
							</div>
							
							<div class="bg-black/30 rounded-lg p-4 border border-white/10">
								<div class="flex items-start gap-4">
									<div class="w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-bold flex-shrink-0">2</div>
									<div>
										<h4 class="text-white font-semibold mb-1">Choose Creation Method</h4>
										<p class="text-sm text-gray-400"><strong>Wizard:</strong> Build step-by-step OR <strong>From Reports:</strong> Paste 2-5 example reports for AI analysis</p>
									</div>
								</div>
							</div>
							
							<div class="bg-black/30 rounded-lg p-4 border border-white/10">
								<div class="flex items-start gap-4">
									<div class="w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-bold flex-shrink-0">3</div>
									<div>
										<h4 class="text-white font-semibold mb-1">Configure Sections</h4>
										<p class="text-sm text-gray-400">Choose which sections to include: Comparison (with/without input field), Technique, Limitations, Clinical History</p>
									</div>
								</div>
							</div>
							
							<div class="bg-black/30 rounded-lg p-4 border border-purple-500/50 ring-2 ring-purple-500/30">
								<div class="flex items-start gap-4">
									<div class="w-10 h-10 rounded-full bg-gradient-to-br from-purple-600 to-blue-600 flex items-center justify-center text-white font-bold flex-shrink-0">4</div>
									<div class="flex-1">
										<div class="flex items-center gap-2 mb-2">
											<h4 class="text-white font-semibold">Findings Setup</h4>
											<span class="px-2 py-0.5 bg-yellow-500/20 text-yellow-300 text-xs rounded-full font-bold">CRITICAL</span>
										</div>
										<p class="text-sm text-gray-300 mb-3">Choose content style (how AI interprets your template) and configure writing style optimizations</p>
										<button 
											onclick={() => expandedTemplateType = expandedTemplateType === 'types' ? null : 'types'}
											class="text-xs text-purple-400 hover:text-purple-300 underline"
										>
											{expandedTemplateType === 'types' ? '− Hide' : '+ Show'} Content Style Options
										</button>
									</div>
								</div>
								
								{#if expandedTemplateType === 'types'}
									<div class="mt-4 grid sm:grid-cols-2 gap-3 animate-fade-in">
										<div class="bg-blue-500/10 rounded p-4 border border-blue-500/30">
											<div class="text-blue-300 font-semibold mb-2 flex items-center gap-2">
												<span class="text-2xl">📋</span>
												<span>Normal Template</span>
											</div>
											<p class="text-xs text-gray-400 mb-3">Paste your normal report as template—AI learns your language and adapts it when pathology is present</p>
											<div class="text-xs text-gray-500 space-y-1">
												<div>✓ Use any normal report</div>
												<div>✓ AI maintains your voice</div>
												<div>✓ Best for general reporting</div>
											</div>
										</div>
										
										<div class="bg-purple-500/10 rounded p-4 border border-purple-500/30">
											<div class="text-purple-300 font-semibold mb-2 flex items-center gap-2">
												<span class="text-2xl">📝</span>
												<span>Guided Template</span>
											</div>
											<p class="text-xs text-gray-400 mb-3">Normal template + embedded // comments to guide AI on what to assess and how to interpret findings</p>
											<div class="text-xs text-gray-500 space-y-1">
												<div>✓ Same as Normal Template</div>
												<div class="text-purple-400">+ // comments provide AI context</div>
												<div>✓ Context-aware assessment</div>
											</div>
										</div>
										
										<div class="bg-green-500/10 rounded p-4 border border-green-500/30">
											<div class="text-green-300 font-semibold mb-2 flex items-center gap-2">
												<span class="text-2xl">📐</span>
												<span>Structured Fill-In</span>
											</div>
											<p class="text-xs text-gray-400 mb-3">Strict placeholder system: {`{VAR}`}, xxx, [opt1/opt2]—template preserved EXACTLY</p>
											<div class="text-xs text-gray-500 space-y-1">
												<div>✓ EXACT template preservation</div>
												<div>✓ Smart form-filling</div>
												<div>✓ High fidelity output</div>
											</div>
										</div>
										
										<div class="bg-orange-500/10 rounded p-4 border border-orange-500/30">
											<div class="text-orange-300 font-semibold mb-2 flex items-center gap-2">
												<span class="text-2xl">✓</span>
												<span>Systematic Checklist</span>
											</div>
											<p class="text-xs text-gray-400 mb-3">Simple bullet list—AI expands each anatomical item systematically</p>
											<div class="text-xs text-gray-500 space-y-1">
												<div>✓ Template is just a list</div>
												<div>✓ AI covers each structure</div>
												<div>✓ Nothing gets missed</div>
											</div>
										</div>
									</div>
								{/if}
							</div>
							
							<div class="bg-black/30 rounded-lg p-4 border border-white/10">
								<div class="flex items-start gap-4">
									<div class="w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-bold flex-shrink-0">5</div>
									<div>
										<h4 class="text-white font-semibold mb-1">Impression Setup</h4>
										<p class="text-sm text-gray-400">Configure verbosity (Brief/Prose), format (prose/bullets/numbered), DDx inclusion, recommendations</p>
									</div>
								</div>
							</div>
							
							<div class="bg-black/30 rounded-lg p-4 border border-white/10">
								<div class="flex items-start gap-4">
									<div class="w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-bold flex-shrink-0">6</div>
									<div>
										<h4 class="text-white font-semibold mb-1">Review & Test</h4>
										<p class="text-sm text-gray-400">Preview complete configuration, test generation with sample data, view syntax highlighting</p>
									</div>
								</div>
							</div>
							
							<div class="bg-black/30 rounded-lg p-4 border border-white/10">
								<div class="flex items-start gap-4">
									<div class="w-10 h-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-bold flex-shrink-0">7</div>
									<div>
										<h4 class="text-white font-semibold mb-1">Save Template</h4>
										<p class="text-sm text-gray-400">Name, description, tags for organization, pin for quick access, global custom instructions</p>
									</div>
								</div>
							</div>
						</div>
					</div>
					
					<!-- Template Writing Guide -->
					<div class="bg-gradient-to-r from-purple-600/10 to-blue-600/10 backdrop-blur-xl border border-purple-500/30 rounded-xl p-8 mb-6">
						<h3 id="template-writing-guide" class="text-xl font-bold text-white mb-4 scroll-mt-24">💡 Template Writing Guide</h3>
						
						<div class="space-y-6">
							<!-- Normal Template Guide -->
							<div class="bg-black/30 rounded-lg p-6 border border-blue-500/30">
								<h4 class="text-blue-300 font-semibold mb-3">📋 Normal Template</h4>
								<p class="text-sm text-gray-300 mb-4">Write brief, standard normal statements using concise, gold-standard language:</p>
								
								<div class="space-y-3 text-xs">
									<div>
										<div class="text-green-400 font-medium mb-1">✓ DO:</div>
										<div class="bg-green-500/10 p-3 rounded border border-green-500/30 text-gray-300">
											"The lungs are clear with no focal consolidation, masses or nodules."<br/>
											"The liver, spleen and pancreas are unremarkable."<br/>
											"The pleural spaces are clear with no effusion or pneumothorax."
										</div>
									</div>
									<div>
										<div class="text-red-400 font-medium mb-1">✗ DON'T (too verbose):</div>
										<div class="bg-red-500/10 p-3 rounded border border-red-500/30 text-gray-400 line-through">
											"The trachea and main bronchi are patent with no endoluminal lesions or significant wall thickening. The carina is sharp and normally positioned."
										</div>
									</div>
								</div>
								
								<div class="mt-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300">
									<strong>Key Principle:</strong> ONE sentence per major structure. Combine related structures. Target 4-6 SHORT paragraphs for entire findings section.
								</div>
							</div>
							
							<!-- Guided Template Guide -->
							<div class="bg-black/30 rounded-lg p-6 border border-purple-500/30">
								<h4 class="text-purple-300 font-semibold mb-3">📝 Guided Template</h4>
								<p class="text-sm text-gray-300 mb-4">Add // comments like colleague annotations—provide context on what to assess:</p>
								
								<div class="bg-purple-500/10 p-4 rounded border border-purple-500/30">
									<code class="text-xs text-gray-300 block whitespace-pre-wrap font-mono">
{`// Comment on study adequacy and technical factors first

The trachea and main bronchi are patent and of normal calibre.
// Assess: endoluminal lesions, extrinsic compression, abnormal tracheal configuration

The mediastinum is of normal width and contour.
// This section covers lymphadenopathy, masses, and vascular structures`}
									</code>
								</div>
								
								<div class="mt-3 p-3 bg-purple-500/10 border border-purple-500/30 rounded text-xs text-purple-300">
									<strong>Comments are stripped from final report</strong>—they only guide AI understanding
								</div>
							</div>
							
							<!-- Structured Template Guide -->
							<div class="bg-black/30 rounded-lg p-6 border border-green-500/30">
								<h4 class="text-green-300 font-semibold mb-3">📐 Structured Fill-In Template</h4>
								<p class="text-sm text-gray-300 mb-4">Use exact placeholder syntax for precise control:</p>
								
								<div class="space-y-3">
									<div class="bg-green-500/10 p-3 rounded border border-green-500/30">
										<div class="text-green-300 font-medium text-xs mb-1">{`{VARNAME}`} Named Variables</div>
										<code class="text-xs text-gray-400 block">LVEF is {`{LVEF}`}%.</code>
										<p class="text-xs text-gray-500 mt-2">Use for specific named values. Limit to 5-7 critical measurements. <span class="text-green-400">Highlighted green</span> if unfilled.</p>
									</div>
									
									<div class="bg-yellow-500/10 p-3 rounded border border-yellow-500/30">
										<div class="text-yellow-300 font-medium text-xs mb-1">xxx Measurement Placeholders</div>
										<code class="text-xs text-gray-400 block">The lesion measures xxx cm in diameter.</code>
										<p class="text-xs text-gray-500 mt-2">Generic measurement blanks (always lowercase). AI extracts from findings. <span class="text-yellow-400">Highlighted yellow</span> if unfilled.</p>
									</div>
									
									<div class="bg-purple-500/10 p-3 rounded border border-purple-500/30">
										<div class="text-purple-300 font-medium text-xs mb-1">[option1/option2] Alternatives</div>
										<code class="text-xs text-gray-400 block mb-2">The ventricle is [normal/dilated/hypertrophied].<br/>Function is [preserved/reduced].</code>
										<div class="text-xs text-gray-500 space-y-1">
											<div class="text-green-400">✓ Brackets wrap ONLY alternative words (2-3 words max)</div>
											<div class="text-red-400">✗ DON'T wrap entire sentences</div>
											<div class="text-purple-400 mt-1">Highlighted purple if not selected</div>
										</div>
									</div>
									
									<div class="bg-blue-500/10 p-3 rounded border border-blue-500/30">
										<div class="text-blue-300 font-medium text-xs mb-1">// instruction AI Instructions</div>
										<code class="text-xs text-gray-400 block mb-2">// Keep all headers in UPPERCASE<br/>// Report only if abnormality present</code>
										<p class="text-xs text-gray-500 mt-2">Actionable AI guidance (stripped from output). Use sparingly at key decision points.</p>
									</div>
								</div>
								
								<div class="mt-4 p-3 bg-green-500/10 border border-green-500/30 rounded text-xs text-green-300">
									<strong>Best Practice:</strong> Test placeholders thoroughly. Keep alternatives simple. Use instructions for conditional logic.
								</div>
							</div>
							
							<!-- Checklist Guide -->
							<div class="bg-black/30 rounded-lg p-6 border border-orange-500/30">
								<h4 class="text-orange-300 font-semibold mb-3">✓ Systematic Checklist</h4>
								<p class="text-sm text-gray-300 mb-4">Create a bullet list with parenthetical guidance:</p>
								
								<div class="bg-orange-500/10 p-4 rounded border border-orange-500/30">
									<code class="text-xs text-gray-300 block whitespace-pre-wrap font-mono">
{`- Lungs (parenchyma, nodules, consolidation, interstitial changes)
- Pleural spaces (effusions, pneumothorax, thickening)
- Mediastinum (lymph nodes, vessels, airways, thymus)
- Heart and pericardium (size, effusion, calcifications)
- Chest wall and bones (soft tissue, ribs, vertebrae)
- Upper abdomen (liver, spleen, adrenals if visible)`}
									</code>
								</div>
								
								<div class="mt-3 p-3 bg-orange-500/10 border border-orange-500/30 rounded text-xs text-orange-300">
									AI generates complete prose for each item systematically
								</div>
							</div>
						</div>
					</div>
					
					<!-- Writing Style Optimizations -->
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8 mb-6">
						<h3 id="writing-style-optimizations" class="text-xl font-bold text-white mb-4 scroll-mt-24">🎯 Writing Style Optimizations</h3>
						<p class="text-gray-300 mb-6">Configure in Step 4 (Findings) and Step 5 (Impression) of wizard, or in the Template Editor's Findings and Impression tabs</p>
						
						<div class="bg-gradient-to-r from-purple-500/10 to-indigo-500/10 rounded-lg p-6 border border-purple-500/30 mb-6">
							<h4 class="text-white font-semibold mb-3">Primary Choice</h4>
							<div class="grid sm:grid-cols-2 gap-3 sm:gap-4">
								<div class="bg-black/20 rounded p-3 sm:p-4 border border-white/10">
									<div class="text-purple-300 font-medium mb-2">🎯 Follow Template Style</div>
									<p class="text-xs text-gray-400">AI matches your template's established voice and sentence structure (best for institutional consistency)</p>
								</div>
								<div class="bg-black/20 rounded p-4 border border-white/10">
									<div class="text-cyan-300 font-medium mb-2">✍️ Choose Writing Style</div>
									<p class="text-xs text-gray-400"><strong class="text-blue-300">Concise</strong> (essentials only) or <strong class="text-purple-300">Prose</strong> (balanced detail)</p>
								</div>
							</div>
						</div>
						
						<div class="grid sm:grid-cols-2 md:grid-cols-3 gap-3 sm:gap-4 mb-6">
							<div class="bg-white/5 rounded-lg p-4 border border-white/10">
								<div class="text-white font-medium mb-2 text-sm">📝 Format</div>
								<p class="text-xs text-gray-400">Prose paragraphs, bullet points, or numbered lists</p>
							</div>
							<div class="bg-white/5 rounded-lg p-4 border border-white/10">
								<div class="text-white font-medium mb-2 text-sm">📋 Finding Sequence</div>
								<p class="text-xs text-gray-400">Clinical priority (critical first) or exact template order</p>
							</div>
							<div class="bg-white/5 rounded-lg p-4 border border-white/10">
								<div class="text-white font-medium mb-2 text-sm">🔍 Clinical Preferences</div>
								<p class="text-xs text-gray-400">Differential diagnosis, recommendations, subsection headers</p>
							</div>
						</div>
					</div>
					
					<!-- Quick Navigation Links -->
					<div class="bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/30 rounded-xl p-6 mt-6">
						<h4 class="text-white font-semibold mb-3">📚 Template Report Generation Sections:</h4>
						<div class="grid sm:grid-cols-2 md:grid-cols-3 gap-3 text-sm">
							<button onclick={() => scrollToSection('using-templates')} class="text-blue-300 hover:text-blue-200 underline text-left">Using Templates</button>
							<button onclick={() => scrollToSection('template-organization')} class="text-blue-300 hover:text-blue-200 underline text-left">Template Organization</button>
							<button onclick={() => scrollToSection('template-editor')} class="text-purple-300 hover:text-purple-200 underline text-left">Template Editor</button>
							<button onclick={() => scrollToSection('creating-templates')} class="text-green-300 hover:text-green-200 underline text-left">Creating Templates (Wizard)</button>
							<button onclick={() => scrollToSection('template-writing-guide')} class="text-orange-300 hover:text-orange-200 underline text-left">Template Writing Guide</button>
							<button onclick={() => scrollToSection('writing-style-optimizations')} class="text-cyan-300 hover:text-cyan-200 underline text-left">Writing Style Optimizations</button>
						</div>
					</div>
				</section>

				<!-- History -->
				<section id="history" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">🕒 History Tab</h2>
					
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-5 sm:p-6 md:p-8 mb-6">
						<h3 class="text-lg sm:text-xl font-bold text-white mb-4">Overview</h3>
						<p class="text-gray-300 mb-4 text-sm sm:text-base">The History tab provides a centralized view of all your generated reports (both Auto Reports and Templated Reports). Access it from the sidebar to browse, search, filter, and manage your complete report library.</p>
						
						<div class="bg-black/30 rounded-lg p-6 border border-purple-500/30 mb-6">
							<h4 class="text-white font-semibold mb-4">Key Features:</h4>
							<ul class="space-y-3 text-sm text-gray-300">
								<li class="flex items-start gap-3">
									<span class="text-green-400 font-bold">✓</span>
									<span><strong class="text-white">Complete Report Library:</strong> All generated reports (Auto and Templated) saved automatically when "Save to History" is enabled in Settings</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-green-400 font-bold">✓</span>
									<span><strong class="text-white">Powerful Search:</strong> Search across report descriptions and content to quickly find specific reports</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-green-400 font-bold">✓</span>
									<span><strong class="text-white">Advanced Filtering:</strong> Filter by report type (Auto/Templated) and date range (Today, Last 7 Days, Last 30 Days, or custom range)</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-green-400 font-bold">✓</span>
									<span><strong class="text-white">Bulk Operations:</strong> Select multiple reports to delete in batch, or delete all filtered results at once</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-green-400 font-bold">✓</span>
									<span><strong class="text-white">Full Report View:</strong> Click "View" on any report to see complete content, version history, and access enhancement features</span>
								</li>
							</ul>
						</div>

						<div class="bg-black/30 rounded-lg p-6 border border-purple-500/30 mb-6">
							<h4 class="text-white font-semibold mb-4">How to Use:</h4>
							<ol class="space-y-3 text-sm text-gray-300">
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">1.</span>
									<span>Access History: Sidebar → <strong>History</strong> tab</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">2.</span>
									<span>Filter Reports (optional):</span>
									<ul class="ml-6 mt-2 space-y-2 text-xs text-gray-400">
										<li>• <strong class="text-blue-300">Search:</strong> Type keywords in the search bar to find reports by description or content</li>
										<li>• <strong class="text-blue-300">Report Type:</strong> Select "Auto Report" or "Templated Report" to filter by type</li>
										<li>• <strong class="text-blue-300">Date Range:</strong> Choose from predefined ranges or select "Custom Range" to pick specific start/end dates</li>
										<li>• <strong class="text-gray-500">Reset Filters:</strong> Click "Reset Filters" button to clear all filters</li>
									</ul>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">3.</span>
									<span>View Reports:</span>
									<ul class="ml-6 mt-2 space-y-2 text-xs text-gray-400">
										<li>• Each report card shows: <strong class="text-green-400">Description/Template name</strong>, <strong class="text-yellow-400">Creation date/time</strong></li>
										<li>• Click <strong class="text-blue-300">"View"</strong> button to open full report viewer with version history and enhancement options</li>
									</ul>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">4.</span>
									<span>Manage Reports:</span>
									<ul class="ml-6 mt-2 space-y-2 text-xs text-gray-400">
										<li>• <strong class="text-red-400">Delete Individual:</strong> Click "Delete" button on any report card (confirmation required)</li>
										<li>• <strong class="text-red-400">Bulk Delete:</strong> Check boxes to select reports, then click "Select All" or manually select, then "Delete Selected (X)"</li>
										<li>• <strong class="text-red-400">Delete All Filtered:</strong> Click "Delete All (X)" to remove all currently filtered reports (confirmation required)</li>
									</ul>
								</li>
							</ol>
						</div>

						<div class="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 mb-4">
							<p class="text-sm text-yellow-300"><strong>💡 Tip:</strong> Reports are automatically saved to History when "Save to History" toggle is enabled in Settings. If disabled, reports are still generated but won't appear in History—useful for temporary/draft reports.</p>
						</div>

						<div class="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
							<p class="text-sm text-blue-300"><strong>📋 Report Cards Display:</strong></p>
							<ul class="mt-2 space-y-1 text-xs text-blue-200">
								<li>• Report description (if provided) or default label (Auto Report/Templated Report)</li>
								<li>• Full creation timestamp (date and time)</li>
								<li>• Checkbox for bulk selection</li>
								<li>• "View" button (opens full report viewer with version history)</li>
								<li>• "Delete" button (permanently removes report)</li>
							</ul>
						</div>
					</div>
				</section>

				<!-- Enhancement -->
				<section id="enhancement" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">✨ Report Enhancement</h2>
					
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8 mb-6">
						<h3 class="text-white font-bold mb-4 text-xl">How to Access Enhancement</h3>
						<div class="bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-lg p-6 border border-purple-500/30">
							<ol class="space-y-3 text-gray-300">
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">1.</span>
									<span>After generating a report, <strong>three enhancement cards appear at the top</strong> of your report</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">2.</span>
									<span>Click any card: <strong class="text-purple-300">Guidelines</strong>, <strong class="text-orange-300">Comparison</strong>, or <strong class="text-blue-300">Chat</strong></span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-purple-400 font-bold">3.</span>
									<span><strong>Sidebar opens on the right</strong> with tabs to navigate between features</span>
								</li>
							</ol>
						</div>
						
						<!-- Visual representation of cards -->
						<div class="mt-6 grid sm:grid-cols-2 md:grid-cols-3 gap-3">
							<div class="bg-gradient-to-br from-purple-900/20 to-purple-800/10 backdrop-blur-xl border border-purple-500/30 rounded-xl p-4">
								<div class="flex items-center gap-2 mb-2">
									<div class="w-10 h-10 rounded-lg bg-purple-600/20 flex items-center justify-center">
										<svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
										</svg>
									</div>
									<div>
										<div class="text-sm font-semibold text-white">Guidelines</div>
										<div class="text-xs text-gray-400">Clinical references</div>
									</div>
								</div>
								<div class="text-xs text-gray-400 mt-2">View 3 guidelines for this report</div>
							</div>
							
							<div class="bg-gradient-to-br from-orange-900/20 to-orange-800/10 backdrop-blur-xl border border-orange-500/30 rounded-xl p-4">
								<div class="flex items-center gap-2 mb-2">
									<div class="w-10 h-10 rounded-lg bg-orange-600/20 flex items-center justify-center">
										<svg class="w-5 h-5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
										</svg>
									</div>
									<div>
										<div class="text-sm font-semibold text-white">Comparison</div>
										<div class="text-xs text-gray-400">Interval analysis</div>
									</div>
								</div>
								<div class="text-xs text-gray-400 mt-2">Compare with prior reports</div>
							</div>
							
							<div class="bg-gradient-to-br from-blue-900/20 to-blue-800/10 backdrop-blur-xl border border-blue-500/30 rounded-xl p-4">
								<div class="flex items-center gap-2 mb-2">
									<div class="w-10 h-10 rounded-lg bg-blue-600/20 flex items-center justify-center">
										<svg class="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
										</svg>
									</div>
									<div>
										<div class="text-sm font-semibold text-white">Chat</div>
										<div class="text-xs text-gray-400">Ask questions & apply edits</div>
									</div>
								</div>
								<div class="text-xs text-gray-400 mt-2">Explore insights and modify your report</div>
							</div>
						</div>
					</div>
					
					<!-- Enhancement Features -->
					<div class="space-y-6">
						<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8">
							<div class="flex items-start gap-4 mb-4">
								<div class="text-4xl">📚</div>
								<div>
									<h3 class="text-white font-bold text-xl mb-2">Clinical Guidelines</h3>
									<p class="text-gray-300 text-sm mb-4">Automatic literature search for each finding in your report</p>
								</div>
							</div>
							
							<div class="bg-gradient-to-r from-teal-500/10 to-cyan-500/10 rounded-lg p-6 border border-teal-500/30">
								<h4 class="text-teal-300 font-semibold mb-3">What You Get:</h4>
								<div class="grid sm:grid-cols-2 gap-3 sm:gap-4 text-sm text-gray-300">
									<div class="space-y-2">
										<div>• <strong>Diagnostic Overview:</strong> Clinical context</div>
										<div>• <strong>Classification Systems:</strong> BI-RADS, Fleischner, Bosniak, LI-RADS</div>
										<div>• <strong>Measurement Protocols:</strong> Standardized techniques with normal ranges</div>
									</div>
									<div class="space-y-2">
										<div>• <strong>Imaging Characteristics:</strong> Key features to identify</div>
										<div>• <strong>Differential Diagnoses:</strong> DDx with imaging features</div>
										<div>• <strong>Follow-up Recommendations:</strong> Modality, timing, specs</div>
										<div>• <strong>Medical References:</strong> Source articles and links</div>
									</div>
								</div>
							</div>
						</div>
						
						<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8">
							<div class="flex items-start gap-4 mb-4">
								<div class="text-4xl">💬</div>
								<div>
									<h3 class="text-white font-bold text-xl mb-2">AI Chat</h3>
									<p class="text-gray-300 text-sm mb-4">Conversational report improvement with surgical edit proposals</p>
								</div>
							</div>
							
							<div class="bg-gradient-to-r from-blue-500/10 to-cyan-500/10 rounded-lg p-6 border border-blue-500/30">
								<h4 class="text-blue-300 font-semibold mb-3">How It Works:</h4>
								<div class="space-y-3 text-sm text-gray-300">
									<div>
										<div class="text-white font-medium mb-1">1. Ask Questions</div>
										<div class="text-xs text-gray-400 bg-black/30 p-2 rounded">"What are the implications of this finding?"</div>
									</div>
									<div>
										<div class="text-white font-medium mb-1">2. Request Edits</div>
										<div class="text-xs text-gray-400 bg-black/30 p-2 rounded">"Expand the impression to include differential diagnoses"</div>
									</div>
									<div>
										<div class="text-white font-medium mb-1">3. Review Proposals</div>
										<div class="text-xs text-gray-400 bg-black/30 p-2 rounded">AI shows: <code class="text-red-300">&lt;&lt;&lt;old text&gt;&gt;&gt;</code> <code class="text-green-300">new text</code> <code class="text-red-300">&lt;&lt;&lt;</code></div>
									</div>
									<div>
										<div class="text-white font-medium mb-1">4. Apply Changes</div>
										<div class="text-xs text-gray-400">Click "Apply" → Changes integrated → New version created</div>
									</div>
								</div>
							</div>
							
							<div class="mt-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300">
								<strong>Features:</strong> Context-aware (knows full report), surgical edits (only changes what's requested), undo/redo via version control
							</div>
						</div>
						
						<div class="bg-yellow-500/10 backdrop-blur-xl border border-yellow-500/30 rounded-xl p-6">
							<div class="flex items-center gap-2 mb-2">
								<svg class="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
								</svg>
								<p class="text-sm text-yellow-300 font-semibold">Completeness Analysis: Currently Inactive</p>
							</div>
							<p class="text-xs text-yellow-400">The completeness analysis feature is temporarily disabled. Focus on Guidelines, Comparison, and Chat for report enhancement.</p>
						</div>
					</div>
				</section>

				<!-- Interval Comparison -->
				<section id="comparison" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">📊 Interval Comparison Analysis</h2>
					
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8 mb-6">
						<p class="text-gray-300 mb-6">AI-powered comparison of your current report against prior scans with automatic change detection, measurement tracking, and revised report generation.</p>
						
						<div class="bg-black/30 rounded-lg p-6 border border-indigo-500/30 mb-6">
							<h3 class="text-white font-semibold mb-4">How to Use:</h3>
							<ol class="space-y-3 text-gray-300 text-sm">
								<li class="flex items-start gap-3">
									<span class="text-orange-400 font-bold">1.</span>
									<span>Click <strong class="text-orange-300">Comparison</strong> card at top of your report</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-orange-400 font-bold">2.</span>
									<span>Sidebar opens → Click <strong>"Add Prior Report"</strong></span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-orange-400 font-bold">3.</span>
									<span>Enter: prior report text, study date (DD/MM/YYYY), scan type</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-orange-400 font-bold">4.</span>
									<span>Add multiple priors if available (AI compares against most recent)</span>
								</li>
								<li class="flex items-start gap-3">
									<span class="text-orange-400 font-bold">5.</span>
									<span>Click <strong>"🔍 Analyse Interval Changes"</strong></span>
								</li>
							</ol>
						</div>
						
						<div class="bg-gradient-to-r from-indigo-500/10 to-purple-500/10 rounded-lg p-6 border border-indigo-500/30">
							<h3 class="text-white font-semibold mb-4">UI Sections Explained:</h3>
							
							<div class="space-y-4">
								<!-- Summary Section -->
								<div class="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
									<h4 class="text-sm font-semibold text-blue-300 mb-2">📊 Summary</h4>
									<p class="text-xs text-gray-300 mb-2">High-level assessment of changes (appears at top)</p>
									<div class="bg-black/30 p-3 rounded text-xs text-gray-400 italic">
										Example: "Interval progression of right upper lobe mass with new mediastinal lymphadenopathy. Stable left pleural effusion."
									</div>
								</div>
								
								<!-- Clinical Analysis Section -->
								<div class="bg-black/30 rounded-lg p-4 border border-white/10">
									<h4 class="text-sm font-semibold text-white mb-3">🔍 Clinical Analysis</h4>
									<p class="text-xs text-gray-400 mb-3">Findings organized by status (collapsible sections):</p>
									
									<div class="space-y-2">
										<details class="bg-red-500/10 border border-red-500/30 rounded p-3">
											<summary class="cursor-pointer text-xs font-medium text-red-300 list-none flex items-center gap-2">
												<span>▶</span>
												<span>🆕 New Findings</span>
												<span class="bg-red-500/30 text-red-200 px-2 py-0.5 rounded">2</span>
											</summary>
											<div class="mt-2 text-xs text-gray-300 space-y-2">
												<div class="bg-black/30 p-2 rounded">
													<div class="font-medium text-white mb-1">Right paratracheal lymphadenopathy</div>
													<div class="text-gray-400">New finding not present in prior study</div>
													<div class="text-yellow-400 mt-1">⚠️ Assessment: Concerning - requires investigation</div>
												</div>
											</div>
										</details>
										
										<details class="bg-yellow-500/10 border border-yellow-500/30 rounded p-3">
											<summary class="cursor-pointer text-xs font-medium text-yellow-300 list-none flex items-center gap-2">
												<span>▶</span>
												<span>📈 Changed Findings</span>
												<span class="bg-yellow-500/30 text-yellow-200 px-2 py-0.5 rounded">1</span>
											</summary>
											<div class="mt-2 text-xs text-gray-300 space-y-2">
												<div class="bg-black/30 p-2 rounded">
													<div class="font-medium text-white mb-1">Right upper lobe nodule</div>
													<div class="flex items-center gap-2 text-xs">
														<span class="text-red-300">Prior: 8mm (15/08/2024)</span>
														<span class="text-gray-500">→</span>
														<span class="text-green-300">Current: 11mm</span>
													</div>
													<div class="text-blue-300 mt-1">Change: +3mm (+37.5%) over 4 months</div>
													<div class="text-orange-400 mt-1">Clinical Significance: Significant growth suggests active process</div>
												</div>
											</div>
										</details>
										
										<details class="bg-green-500/10 border border-green-500/30 rounded p-3">
											<summary class="cursor-pointer text-xs font-medium text-green-300 list-none flex items-center gap-2">
												<span>▶</span>
												<span>✅ Stable Findings</span>
												<span class="bg-green-500/30 text-green-200 px-2 py-0.5 rounded">1</span>
											</summary>
										</details>
									</div>
								</div>
								
								<!-- Report Modifications Section -->
								<div class="bg-black/30 rounded-lg p-4 border border-white/10">
									<h4 class="text-sm font-semibold text-white mb-3">📝 Report Modifications</h4>
									<p class="text-xs text-gray-400 mb-3">Shows what will change in revised report:</p>
									
									<div class="space-y-2">
										<div class="bg-white/5 rounded p-3 border border-white/10">
											<div class="text-xs text-gray-400 mb-2 font-medium">Reason: Document interval growth</div>
											<div class="bg-red-500/10 border border-red-500/30 rounded p-2 mb-2">
												<div class="text-xs text-red-400 mb-1">Original:</div>
												<div class="text-xs text-gray-300 line-through">There is an 11mm nodule in the left upper lobe.</div>
											</div>
											<div class="bg-green-500/10 border border-green-500/30 rounded p-2">
												<div class="text-xs text-green-400 mb-1">Revised:</div>
												<div class="text-xs text-gray-300">There is an 11mm nodule in the left upper lobe, increased from 8mm on 15/08/2024 CT chest, representing interval growth over 4 months.</div>
											</div>
										</div>
									</div>
								</div>
								
								<!-- Action Buttons -->
								<div class="bg-black/30 rounded-lg p-4 border border-purple-500/30">
									<h4 class="text-white font-semibold mb-3 text-sm">Available Actions:</h4>
									<div class="space-y-2">
										<div class="bg-purple-500/10 border border-purple-500/30 rounded p-3 text-xs text-purple-300">
											<strong>👁️ Preview Full Revised Report:</strong> Opens modal with complete revised report
										</div>
										<div class="bg-green-500/10 border border-green-500/30 rounded p-3 text-xs text-green-300">
											<strong>✅ Apply Comparison Report:</strong> One-click application (creates new version)
										</div>
										<div class="bg-gray-500/10 border border-gray-500/30 rounded p-3 text-xs text-gray-400">
											<strong>🗑️ Clear Comparison:</strong> Remove prior reports and start over
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</section>

				<!-- Quality Control -->
				<section id="quality-control" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">🎯 Quality Control</h2>
					
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8">
						<p class="text-gray-300 mb-6">Automatic detection of missing information and unfilled placeholders in structured templates.</p>
						
						<h3 class="text-white font-semibold mb-4">Placeholder Types Detected:</h3>
						<div class="grid sm:grid-cols-2 gap-3 sm:gap-4 mb-6">
							<div class="bg-green-500/10 rounded-lg p-4 border border-green-500/30">
								<div class="text-green-300 font-semibold mb-2">{`{VARIABLE}`} Named Variables</div>
								<p class="text-xs text-gray-400 mb-2">Example: <code class="bg-black/30 px-1 rounded text-green-300">LVEF is {`{LVEF}`}%</code></p>
								<p class="text-xs text-gray-400"><span class="inline-block w-3 h-3 bg-green-500 rounded mr-1"></span>Highlighted in green if not filled</p>
							</div>
							
							<div class="bg-yellow-500/10 rounded-lg p-4 border border-yellow-500/30">
								<div class="text-yellow-300 font-semibold mb-2">xxx Measurements</div>
								<p class="text-xs text-gray-400 mb-2">Example: <code class="bg-black/30 px-1 rounded text-yellow-300">measures xxx cm</code></p>
								<p class="text-xs text-gray-400"><span class="inline-block w-3 h-3 bg-yellow-500 rounded mr-1"></span>Highlighted in yellow if not filled</p>
							</div>
							
							<div class="bg-purple-500/10 rounded-lg p-4 border border-purple-500/30">
								<div class="text-purple-300 font-semibold mb-2">[option1/option2] Alternatives</div>
								<p class="text-xs text-gray-400 mb-2">Example: <code class="bg-black/30 px-1 rounded text-purple-300">[normal/dilated]</code></p>
								<p class="text-xs text-gray-400"><span class="inline-block w-3 h-3 bg-purple-500 rounded mr-1"></span>Highlighted in purple if not selected</p>
							</div>
							
							<div class="bg-orange-500/10 rounded-lg p-4 border border-orange-500/30">
								<div class="text-orange-300 font-semibold mb-2">Blank Sections</div>
								<p class="text-xs text-gray-400 mb-2">Sections that should have content but are empty</p>
								<p class="text-xs text-gray-400"><span class="inline-block w-3 h-3 bg-orange-500 rounded mr-1"></span>Highlighted in orange</p>
							</div>
						</div>
						
						<div class="bg-gradient-to-r from-green-500/10 to-emerald-500/10 rounded-lg p-6 border border-green-500/30">
							<h4 class="text-white font-semibold mb-3">How to Fill Placeholders:</h4>
							<div class="space-y-2 text-sm text-gray-300">
								<div class="flex items-start gap-2">
									<span class="text-green-400">1.</span>
									<span><strong>Hover</strong> over highlighted item → Popup appears showing type and context</span>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-green-400">2.</span>
									<span><strong>Choose fill method:</strong></span>
								</div>
								<div class="ml-6 space-y-2">
									<div class="bg-blue-500/10 p-3 rounded border border-blue-500/30 text-xs">
										<strong class="text-blue-300">Manual Entry:</strong> Type or paste value directly
									</div>
									<div class="bg-purple-500/10 p-3 rounded border border-purple-500/30 text-xs">
										<strong class="text-purple-300">AI Suggestion:</strong> Click "Fill with AI" → AI analyzes context → Proposes value → Review and accept/modify
									</div>
								</div>
								<div class="flex items-start gap-2">
									<span class="text-green-400">3.</span>
									<span><strong>Apply</strong> → Highlight removed, report updated</span>
								</div>
							</div>
						</div>
					</div>
				</section>

				<!-- Version Control -->
				<section id="version-control" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">🔄 Version Control</h2>
					
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8 mb-6">
						<p class="text-gray-300 mb-6">Every report maintains complete version history. Access via version icon at top-right of report.</p>
						
						<div class="bg-black/30 rounded-lg p-6 border border-purple-500/30 mb-6">
							<h3 class="text-white font-semibold mb-4">Version Labels You'll See:</h3>
							<p class="text-sm text-gray-400 mb-4">Versions are automatically tagged based on how they were created:</p>
							<div class="grid sm:grid-cols-2 gap-2 sm:gap-3 text-xs">
								<div class="bg-purple-500/10 p-3 rounded border border-purple-500/30">
									<div class="flex items-center gap-2 mb-1">
										<span class="px-2 py-0.5 rounded-full bg-purple-500/30 text-purple-200 font-medium">Current</span>
									</div>
									<div class="text-gray-400">The version you're currently viewing</div>
								</div>
								<div class="bg-blue-500/10 p-3 rounded border border-blue-500/30">
									<div class="flex items-center gap-2 mb-1">
										<span class="px-2 py-0.5 rounded-full bg-blue-500/30 text-blue-200 font-medium">Manual Edit</span>
									</div>
									<div class="text-gray-400">After you manually edited the report content</div>
								</div>
								<div class="bg-green-500/10 p-3 rounded border border-green-500/30">
									<div class="flex items-center gap-2 mb-1">
										<span class="px-2 py-0.5 rounded-full bg-green-500/30 text-green-200 font-medium">Chat Edit</span>
									</div>
									<div class="text-gray-400">After applying AI chat suggestions</div>
								</div>
								<div class="bg-amber-500/10 p-3 rounded border border-amber-500/30">
									<div class="flex items-center gap-2 mb-1">
										<span class="px-2 py-0.5 rounded-full bg-amber-500/30 text-amber-200 font-medium">Comparison Edit</span>
									</div>
									<div class="text-gray-400">After applying interval comparison changes</div>
								</div>
							</div>
							<p class="text-xs text-gray-500 mt-4"><strong>Note:</strong> First report generation and restored versions don't show a special label, only "Current" if active.</p>
						</div>
						
						<div class="bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-lg p-6 border border-purple-500/30">
							<h3 class="text-white font-semibold mb-4">Version Operations:</h3>
							
							<div class="space-y-4">
								<div class="bg-black/30 p-4 rounded border border-white/10">
									<div class="text-white font-medium mb-2 text-sm">📋 List Versions</div>
									<p class="text-xs text-gray-400">Shows all versions chronologically with timestamps, version numbers, and change tags. Current version clearly marked.</p>
								</div>
								
								<div class="bg-black/30 p-4 rounded border border-white/10">
									<div class="text-white font-medium mb-2 text-sm">👁️ View Version</div>
									<p class="text-xs text-gray-400">Click version to expand → Full content displayed with markdown rendering</p>
								</div>
								
								<div class="bg-black/30 p-4 rounded border border-purple-500/30">
									<div class="text-purple-300 font-medium mb-2 text-sm">🔀 Compare Versions (Visual Diff)</div>
									<div class="space-y-2 text-xs text-gray-300">
										<div>1. Toggle "Show Diff View" button</div>
										<div>2. Select two versions to compare</div>
										<div>3. Side-by-side or inline diff display:</div>
										<div class="mt-2 bg-black/30 p-3 rounded space-y-1">
											<div><span class="bg-green-500/30 text-green-200 px-1 rounded">Green highlight</span> = Additions</div>
											<div><span class="bg-red-500/30 text-red-200 px-1 rounded line-through">Red highlight</span> = Deletions</div>
											<div><span class="text-gray-400">Gray text</span> = Unchanged</div>
										</div>
									</div>
								</div>
								
								<div class="bg-black/30 p-4 rounded border border-white/10">
									<div class="text-white font-medium mb-2 text-sm">↩️ Restore Version</div>
									<p class="text-xs text-gray-400">Click "Restore" on any version → Creates new version (doesn't delete history) → New version tagged as "restored"</p>
								</div>
							</div>
						</div>
					</div>
				</section>

				<!-- Dictation -->
				<section id="dictation" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">🎤 Voice Dictation</h2>
					
					<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8">
						<p class="text-gray-300 mb-6">Medical-grade voice transcription using Deepgram Nova-3 Medical model. Must be configured in Settings first.</p>
						
						<div class="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 mb-6">
							<p class="text-sm text-yellow-300"><strong>⚠️ Setup Required:</strong> You must configure your Deepgram API key in Settings before using dictation features.</p>
						</div>
						
						<div class="grid sm:grid-cols-2 gap-4 sm:gap-6 mb-6">
							<div class="bg-gradient-to-r from-blue-500/10 to-cyan-500/10 rounded-lg p-5 sm:p-6 border border-blue-500/30">
								<h3 class="text-white font-semibold mb-3">🌊 Streaming Mode</h3>
								<p class="text-xs text-gray-400 mb-4">Real-time transcription as you speak (default)</p>
								<ol class="space-y-2 text-xs text-gray-300">
									<li>1. Click microphone icon (🎤) in text field</li>
									<li>2. Grant browser microphone permission</li>
									<li>3. Speak your findings</li>
									<li>4. Transcript appears <strong>in real-time</strong></li>
									<li>5. Click stop when done</li>
								</ol>
							</div>
							
							<div class="bg-gradient-to-r from-purple-500/10 to-pink-500/10 rounded-lg p-6 border border-purple-500/30">
								<h3 class="text-white font-semibold mb-3">⏸️ Batch Mode</h3>
								<p class="text-xs text-gray-400 mb-4">Generate text after recording completes</p>
								<ol class="space-y-2 text-xs text-gray-300">
									<li>1. Click microphone icon (🎤)</li>
									<li>2. Record complete finding</li>
									<li>3. Click stop</li>
									<li>4. Transcript generated and inserted</li>
								</ol>
							</div>
						</div>
						
						<div class="bg-gradient-to-r from-green-500/10 to-emerald-500/10 rounded-lg p-6 border border-green-500/30">
							<h4 class="text-white font-semibold mb-3">Features:</h4>
							<ul class="grid sm:grid-cols-2 gap-2 text-sm text-gray-300">
								<li>• Medical vocabulary optimized</li>
								<li>• Automatic punctuation</li>
								<li>• Real-time streaming (streaming mode)</li>
								<li>• Error handling & recovery</li>
								<li>• Toggle between streaming/batch in Settings</li>
							</ul>
						</div>
					</div>
				</section>

				<!-- Settings -->
				<section id="settings" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">⚙️ Settings & Configuration</h2>
					
					<div class="space-y-6">
						<!-- Dictation Setup -->
						<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8">
							<h3 class="text-xl font-bold text-white mb-4">🎤 Dictation Setup (Deepgram API Key)</h3>
							<p class="text-gray-300 mb-6">Configure your personal Deepgram API key to enable voice transcription features.</p>
							
							<div class="bg-gradient-to-r from-purple-500/10 to-blue-500/10 rounded-lg p-6 border border-purple-500/30">
								<h4 class="text-white font-semibold mb-4">Step-by-Step Setup:</h4>
								<ol class="space-y-3 text-sm text-gray-300">
									<li class="flex items-start gap-3">
										<span class="text-purple-400 font-bold">1.</span>
										<span>Go to <a href="https://console.deepgram.com/" target="_blank" class="text-purple-400 hover:text-purple-300 underline">Deepgram Console</a> (opens in new tab)</span>
									</li>
									<li class="flex items-start gap-3">
										<span class="text-purple-400 font-bold">2.</span>
										<span>Create account or log in</span>
									</li>
									<li class="flex items-start gap-3">
										<span class="text-purple-400 font-bold">3.</span>
										<span>Navigate to API Keys section</span>
									</li>
									<li class="flex items-start gap-3">
										<span class="text-purple-400 font-bold">4.</span>
										<span>Create new API key or copy existing key</span>
									</li>
									<li class="flex items-start gap-3">
										<span class="text-purple-400 font-bold">5.</span>
										<span>In RadFlow Settings → API Keys → Paste key in <strong>"Deepgram API Key"</strong> field</span>
									</li>
									<li class="flex items-start gap-3">
										<span class="text-purple-400 font-bold">6.</span>
										<span>Click <strong>Save Settings</strong></span>
									</li>
									<li class="flex items-start gap-3">
										<span class="text-purple-400 font-bold">7.</span>
										<span>Microphone icons now active throughout the app!</span>
									</li>
								</ol>
							</div>
							
							<div class="mt-4 bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-blue-300">
								<strong>Note:</strong> API key is encrypted and stored securely. You can clear it anytime with the "Clear" button.
							</div>
						</div>
						
						<!-- Other Settings -->
						<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl p-8">
							<h3 class="text-xl font-bold text-white mb-4">⚙️ Other Settings</h3>
							
							<div class="space-y-4">
								<div class="bg-black/30 rounded-lg p-4 border border-white/10">
									<div class="text-white font-medium mb-2">👤 User Information</div>
									<p class="text-sm text-gray-400">Full name and signature for report sign-off (automatically added to generated reports)</p>
								</div>
								
								<div class="bg-black/30 rounded-lg p-4 border border-white/10">
									<div class="text-white font-medium mb-2">💾 Auto-Save Reports</div>
									<p class="text-sm text-gray-400">Toggle on/off: When enabled, all generated reports are automatically saved to History</p>
								</div>
								
								<div class="bg-black/30 rounded-lg p-4 border border-purple-500/30">
									<div class="text-purple-300 font-medium mb-2">🎤 Dictation Mode</div>
									<p class="text-sm text-gray-400 mb-2">Choose transcription behavior:</p>
									<div class="ml-4 space-y-2 text-xs text-gray-400">
										<div>• <strong class="text-blue-300">Streaming:</strong> Transcript appears in real-time as you speak</div>
										<div>• <strong class="text-purple-300">Batch:</strong> Transcript generated after you finish recording</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</section>

				<!-- FAQ -->
				<section id="faq" class="scroll-mt-24">
					<h2 class="text-2xl sm:text-3xl font-bold text-white mb-6">❓ Frequently Asked Questions</h2>
					
					<div class="space-y-4">
						{#each faqs as faq, idx}
							<div class="bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl overflow-hidden hover:border-white/20 transition-all">
								<button
									onclick={() => expandedFaq = expandedFaq === idx ? null : idx}
									class="w-full text-left p-5 sm:p-6 hover:bg-white/5 transition-colors flex items-center justify-between gap-4"
								>
									<span class="text-white font-semibold text-sm sm:text-base">{faq.q}</span>
									<svg class="w-5 h-5 text-gray-400 transition-transform flex-shrink-0 {expandedFaq === idx ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
									</svg>
								</button>
								{#if expandedFaq === idx}
									<div class="px-5 sm:px-6 pb-5 sm:pb-6 text-gray-300 text-sm sm:text-base leading-relaxed animate-fade-in prose prose-invert prose-sm max-w-none">
										{@html formatFaqAnswer(faq.a)}
									</div>
								{/if}
							</div>
						{/each}
					</div>
					
					<div class="mt-8 bg-gradient-to-r from-purple-600/20 to-blue-600/20 backdrop-blur-xl border border-purple-500/30 rounded-xl p-6 sm:p-8 text-center">
						<h3 class="text-xl sm:text-2xl font-bold text-white mb-4">Need More Help?</h3>
						<p class="text-gray-300 mb-6">Can't find what you're looking for? We're here to help!</p>
						<div class="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4">
							<a href="/register" class="w-full sm:w-auto px-6 py-3 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-lg font-medium hover:from-purple-500 hover:to-blue-500 transition-all text-center">
								Try RadFlow Now
							</a>
							<a href="/" class="w-full sm:w-auto px-6 py-3 bg-white/10 text-white rounded-lg font-medium hover:bg-white/20 transition-all border border-white/20 text-center">
								Back to Home
							</a>
						</div>
					</div>
				</section>
			</main>
		</div>
	</div>
	
	<!-- Footer -->
	<footer class="border-t border-white/10 py-8 mt-12">
		<div class="max-w-7xl mx-auto px-4 sm:px-6 text-center text-gray-400 text-xs sm:text-sm">
			<p>© 2026 H&A LABS LTD | Company No. 16114480</p>
			<p class="mt-2">RadFlow is currently in beta. Free to use during development.</p>
		</div>
	</footer>
</div>

<style>
	@keyframes fadeIn {
		from {
			opacity: 0;
			transform: translateY(-10px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
	
	@keyframes slideInLeft {
		from {
			transform: translateX(-100%);
		}
		to {
			transform: translateX(0);
		}
	}
	
	.animate-fade-in {
		animation: fadeIn 0.3s ease-out;
	}
	
	.animate-slide-in-left {
		animation: slideInLeft 0.3s ease-out;
	}
	
	code {
		font-family: 'Monaco', 'Courier New', monospace;
		font-size: 0.9em;
	}
	
	:global(html) {
		scroll-behavior: smooth;
	}
	
	.scroll-mt-24 {
		scroll-margin-top: 6rem;
	}
	
	/* Styling for details/summary */
	details > summary {
		list-style: none;
	}
	
	details > summary::-webkit-details-marker {
		display: none;
	}
	
	details[open] summary svg {
		transform: rotate(90deg);
	}
	
	/* Simple, clean code styling */
	:global(.prose code) {
		background-color: rgba(255, 255, 255, 0.1);
		padding: 0.125rem 0.375rem;
		border-radius: 0.25rem;
		font-size: 0.875em;
		font-family: 'Monaco', 'Courier New', monospace;
		color: #c084fc;
		font-weight: normal;
	}
	
	:global(.prose strong) {
		color: #ffffff;
		font-weight: 600;
	}
	
	:global(.prose a) {
		color: #60a5fa;
		text-decoration: none;
	}
	
	:global(.prose a:hover) {
		text-decoration: underline;
	}
	
	:global(.prose ol) {
		list-style-type: decimal;
		padding-left: 1.5rem;
		margin-top: 0.75rem;
		margin-bottom: 0.75rem;
	}
	
	:global(.prose ol li) {
		margin-bottom: 0.5rem;
		padding-left: 0.25rem;
	}
	
	:global(.prose p) {
		margin-bottom: 0.75rem;
	}
</style>
