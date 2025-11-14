<script>
	let visible = false;
	let message = '';
	let timeout;

	export function show(msg, duration = 3000) {
		message = msg;
		visible = true;
		
		if (timeout) clearTimeout(timeout);
		timeout = setTimeout(() => {
			visible = false;
		}, duration);
	}

	export function hide() {
		visible = false;
	}
</script>

{#if visible}
	<div class="fixed bottom-4 right-4 z-50 animate-slide-up">
		<div class="bg-purple-600 text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 min-w-[200px]">
			<svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
			</svg>
			<span class="text-sm font-medium">{message}</span>
		</div>
	</div>
{/if}

<style>
	@keyframes slide-up {
		from {
			transform: translateY(100%);
			opacity: 0;
		}
		to {
			transform: translateY(0);
			opacity: 1;
		}
	}

	.animate-slide-up {
		animation: slide-up 0.3s ease-out;
	}
</style>

