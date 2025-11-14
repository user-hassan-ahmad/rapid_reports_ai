/**
 * API Configuration
 * Uses Vercel system variables and custom PUBLIC_API_URL
 * Falls back to localhost for development
 */

// Try custom env var first, then use hardcoded production URL for Vercel deployments
const envApiUrl = import.meta.env.PUBLIC_API_URL;
const isProduction = import.meta.env.PROD;
const isDevelopment = import.meta.env.DEV;

// For production deployments, use the hardcoded API URL since environment variables aren't being injected
// For development, use localhost
export const API_URL = envApiUrl || (isProduction ? 'https://rad-flow.uk' : 'http://localhost:8000');

// Debug: Always log API URL to help troubleshoot
console.log('🔍 API Configuration:', {
	API_URL,
	PUBLIC_API_URL: envApiUrl,
	MODE: import.meta.env.MODE,
	DEV: isDevelopment,
	PROD: isProduction,
	VERCEL_ENV: import.meta.env.VERCEL_ENV
});

