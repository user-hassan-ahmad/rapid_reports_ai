/**
 * API Configuration
 * Uses environment variable PUBLIC_API_URL, falls back to localhost for development
 */
const envApiUrl = import.meta.env.PUBLIC_API_URL;
export const API_URL = envApiUrl || 'http://localhost:8000';

// Debug: Always log API URL (including production) to help troubleshoot
console.log('🔍 API Configuration:', {
	API_URL,
	PUBLIC_API_URL: envApiUrl,
	MODE: import.meta.env.MODE,
	DEV: import.meta.env.DEV,
	PROD: import.meta.env.PROD
});

