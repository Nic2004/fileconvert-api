# FileConvert API - Server

## Deploy pe Render.com (15 minute)

### Pasul 1 - GitHub
1. Creează cont pe github.com (dacă nu ai)
2. Creează un repository nou numit `fileconvert-api`
3. Încarcă toate fișierele din acest folder

### Pasul 2 - Render
1. Mergi pe render.com → Sign Up cu contul GitHub
2. Click "New +" → "Web Service"
3. Conectează repository-ul `fileconvert-api`
4. Render detectează automat Dockerfile-ul
5. Plan: **Starter (7$/lună)**
6. Click "Deploy"

### Pasul 3 - URL
După ~5 minute primești URL-ul:
`https://fileconvert-api.onrender.com`

Pune acest URL în extensia Chrome (fișierul api/converter.js)

## Testare locală (opțional)
```bash
docker build -t fileconvert .
docker run -p 8000:8000 fileconvert
# Accesează: http://localhost:8000
```

## Endpoint-uri API

| Method | URL | Descriere |
|--------|-----|-----------|
| GET | / | Status server |
| GET | /health | Health check |
| GET | /formats | Formate suportate |
| POST | /convert | Convertește fișier |

## Exemplu conversie (POST /convert)
```javascript
const formData = new FormData();
formData.append('file', fisierulTau);
formData.append('target_format', 'pdf');

const response = await fetch('https://fileconvert-api.onrender.com/convert', {
  method: 'POST',
  body: formData
});

const blob = await response.blob();
// descarcă blob ca fișier
```
