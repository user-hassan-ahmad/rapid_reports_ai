/**
 * API Configuration
 * Uses environment variable PUBLIC_API_URL, falls back to localhost for development
 */
const envApiUrl = import.meta.env.PUBLIC_API_URL;
export const API_URL = envApiUrl || 'http://localhost:8000';

// Debug: Log API URL in development
if (import.meta.env.DEV) {
	console.log('🔍 API_URL:', API_URL, '| PUBLIC_API_URL env:', envApiUrl);
}

