/**
 * API Configuration
 * Uses environment variable PUBLIC_API_URL, falls back to localhost for development
 */
export const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';

