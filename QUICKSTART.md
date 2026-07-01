# Quick Start Guide / Guía Rápida

**English below Spanish.** *(El inglés está debajo del español.)*

---

## 🇪🇸 Español

### Lo básico

Todo se pide con **un solo comando**, escribiendo lo que quieres en lenguaje
normal — español o inglés, el motor detecta el idioma automáticamente:

```powershell
python pedir.py "tu peticion aqui"
```

### Ejemplos que puedes copiar y pegar

**Sesión individual:**
```powershell
python pedir.py "resistencia aerobica de 1 hora"
python pedir.py "tempo de 50 minutos"
python pedir.py "vo2 max de 45 minutos"
python pedir.py "umbral de 40 minutos por frecuencia cardiaca"
python pedir.py "sweet spot de 1 hora, TSS 70"
```

**Progresión (varias sesiones que avanzan):**
```powershell
python pedir.py "una progresion de tempo empezando en 30 minutos"
python pedir.py "progresion de sweet spot, inicio 40 min, maximo 90 min"
```

### Cómo pedir bien

| Quieres decir | Cómo lo escribes |
|---|---|
| Zona de entrenamiento | El nombre en español normal: "resistencia aeróbica", "tempo", "sweet spot", "umbral", "vo2 max", "anaeróbico", "neuromuscular" |
| Duración | "de 1 hora", "de 45 minutos", "50 min" |
| Por potencia (default) | No necesitas decir nada — es lo normal |
| Por frecuencia cardiaca | Agrega "por frecuencia cardiaca" o "por pulso" |
| Progresión | Empieza con "una progresión de..." |
| Duración inicial + máxima | "empezando en 30 min" + "máximo 90 min" |
| Un TSS específico | "TSS 70" en cualquier parte de la frase |

**No necesitas saber los nombres técnicos internos** (como `Endurance` o
`SubThreshold`) — el motor los traduce automáticamente.

### Qué esperar cuando ejecutas el comando

1. `Interpretando / Interpreting...` — el motor está leyendo tu petición.
2. `Entendí: ...` — confirma qué entendió. **Revisa esta línea** — si algo no
   coincide con lo que querías, puedes cancelar (Ctrl+C) y volver a escribir
   tu petición de forma más clara.
3. `Generando... (Claude esta razonando)` — espera unos segundos.
4. El entrenamiento completo aparece en pantalla, en sintaxis de intervals.icu.
5. Se guarda automáticamente en un archivo `.md` en la misma carpeta
   (`workout_XXXXXXXX.md` para sesiones, o una carpeta `progression_XXX/` con
   una sesión por archivo si pediste una progresión).

### Subir el entrenamiento a intervals.icu

1. Abre el archivo `.md` generado (con el Bloc de notas, por ejemplo) y copia
   todo su contenido.
2. En intervals.icu, ve a **Workouts → New Workout** (o similar).
3. Pega el contenido en el editor de workouts — reconoce la sintaxis
   directamente.

### Problemas comunes

- **"Entendí" no coincide con lo que pediste** → sé más específico. Por
  ejemplo, en vez de "algo suave" escribe "resistencia aeróbica de 45 min".
- **Error de interpretación / generación** → revisa que tu `ANTHROPIC_API_KEY`
  esté configurada (ver `docs/SETUP.md`) y que tengas crédito disponible en
  [console.anthropic.com](https://console.anthropic.com).
- **Quieres repetir algo similar a un entrenamiento pasado** → simplemente
  vuelve a pedirlo; el motor consulta su propio catálogo (`my_catalog.sqlite`)
  como memoria para razonar variedad, sin que tengas que decirle nada extra.

---

## 🇬🇧 English

### The basics

Everything is requested with **a single command**, writing what you want in
plain language — Spanish or English, the engine auto-detects the language:

```powershell
python pedir.py "your request here"
```

### Copy-paste examples

**Single session:**
```powershell
python pedir.py "aerobic endurance for 1 hour"
python pedir.py "tempo for 50 minutes"
python pedir.py "vo2 max for 45 minutes"
python pedir.py "threshold for 40 minutes by heart rate"
python pedir.py "sweet spot for 1 hour, TSS 70"
```

**Progression (multiple sessions that progress):**
```powershell
python pedir.py "a tempo progression starting at 30 minutes"
python pedir.py "sweet spot progression, start 40 min, max 90 min"
```

### How to phrase your request

| You want to say | How to write it |
|---|---|
| Training zone | Plain English name: "aerobic endurance", "tempo", "sweet spot", "threshold", "vo2 max", "anaerobic", "neuromuscular" |
| Duration | "for 1 hour", "for 45 minutes", "50 min" |
| By power (default) | You don't need to say anything — it's the default |
| By heart rate | Add "by heart rate" or "by pulse/HR" |
| Progression | Start with "a progression of..." |
| Initial + max duration | "starting at 30 min" + "max 90 min" |
| A specific TSS | "TSS 70" anywhere in the sentence |

**You never need to know the internal technical names** (like `Endurance` or
`SubThreshold`) — the engine translates automatically.

### What to expect when you run the command

1. `Interpretando / Interpreting...` — the engine is reading your request.
2. `Understood: ...` — confirms what it understood. **Check this line** — if
   it doesn't match what you wanted, cancel (Ctrl+C) and rephrase more clearly.
3. `Generating... (Claude is reasoning)` — wait a few seconds.
4. The complete workout appears on screen, in intervals.icu syntax.
5. It's automatically saved to a `.md` file in the same folder
   (`workout_XXXXXXXX.md` for single sessions, or a `progression_XXX/` folder
   with one session per file if you requested a progression).

### Uploading the workout to intervals.icu

1. Open the generated `.md` file (Notepad, for example) and copy its content.
2. In intervals.icu, go to **Workouts → New Workout** (or similar).
3. Paste the content into the workout editor — it recognizes the syntax
   directly.

### Common issues

- **"Understood" doesn't match what you asked** → be more specific. Instead
  of "something easy," write "aerobic endurance for 45 min".
- **Interpretation/generation error** → check that your `ANTHROPIC_API_KEY` is
  set (see `docs/SETUP.md`) and that you have credit at
  [console.anthropic.com](https://console.anthropic.com).
- **Want something similar to a past workout** → just ask again; the engine
  consults its own catalog (`my_catalog.sqlite`) as memory to reason variety,
  with nothing extra needed from you.
