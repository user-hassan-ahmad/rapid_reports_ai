/**
 * Development-only logger utility
 * Only logs in development mode to avoid cluttering production console
 */

const isDev = import.meta.env.DEV;

export const logger = {
	error: (...args) => {
		if (isDev) {
			console.error(...args);
		}
	},
	log: (...args) => {
		if (isDev) {
			console.log(...args);
		}
	},
	warn: (...args) => {
		if (isDev) {
			console.warn(...args);
		}
	}
};

