# Rapid Reports AI - Frontend

SvelteKit frontend for the Rapid Reports AI application.

> **📖 For complete setup instructions, see the main [README.md](../README.md) and [SETUP.md](../SETUP.md)**

## Quick Start

1. Install dependencies:
```bash
cd frontend
npm install
# or
bun install
```

2. Start development server:
```bash
npm run dev
```

The frontend will be available at `http://localhost:5173`

## Development

### Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run preview` - Preview production build
- `npm run check` - Type check with Svelte
- `npm run lint` - Lint code
- `npm run format` - Format code with Prettier
- `npm run test` - Run tests

### Tech Stack

- **Framework**: SvelteKit
- **Styling**: TailwindCSS
- **Build Tool**: Vite
- **State Management**: Svelte stores
- **Markdown**: marked

### Project Structure

```
frontend/
├── src/
│   ├── lib/
│   │   ├── components/     # Reusable components
│   │   ├── stores/         # Svelte stores (auth, dictation)
│   │   └── utils/          # Utility functions
│   └── routes/
│       ├── components/     # Page-specific components
│       ├── login/          # Login page
│       ├── register/       # Registration page
│       └── +page.svelte    # Main application page
├── static/                 # Static assets
└── package.json
```

## Configuration

### API URL

The frontend connects to the backend API at `http://localhost:8000` by default. To change this, update the `API_URL` constant in:
- `src/routes/+page.svelte`

### Environment Variables

For production builds, you may want to use environment variables. Create a `.env` file:

```env
PUBLIC_API_URL=http://localhost:8000
```

Access in code with `import.meta.env.PUBLIC_API_URL`.

## Building for Production

```bash
npm run build
npm run preview
```

The built files will be in the `build` directory.

## Features

- **Authentication**: Login, registration, password reset
- **Auto Reports**: Generate reports from pre-built templates
- **Custom Templates**: Create and manage custom report templates
- **Report Enhancement**: AI-powered report improvement
- **Report History**: View and manage generated reports
- **Real-time Dictation**: Medical transcription via WebSocket
- **Settings**: User preferences and API key management

For detailed setup instructions, see the main [SETUP.md](../SETUP.md).
