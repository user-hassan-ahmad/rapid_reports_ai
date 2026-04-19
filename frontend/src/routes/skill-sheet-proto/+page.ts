import { requireDevRoute } from '$lib/guards/dev-route';

export const load = () => requireDevRoute();
