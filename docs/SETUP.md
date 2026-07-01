# Setup Guide (Windows, no assumptions)

This walks through everything needed to run `cycling-workout-engine` from
zero, assuming nothing is already installed or configured.

## 1. Get the code

```
git clone <repo-url> cycling-workout-engine
cd cycling-workout-engine\workout_engine
```

(If you received this as a `.zip` instead of cloning, extract it to a path
with no spaces or accented characters, e.g. `E:\Dev\github\cycling-workout-engine`.)

## 2. Check Python

Open **PowerShell** (Windows key → type `powershell` → Enter), navigate to
the project folder, and check your Python version:

```powershell
cd E:\Dev\github\cycling-workout-engine\workout_engine
python --version
```

Python 3.10 or newer is required. If it's not installed, get it from
[python.org](https://www.python.org/downloads/) or the Microsoft Store.

## 3. Install dependencies

```powershell
pip install anthropic pytest jsonschema
```

## 4. Run the test suite (no API key needed yet)

```powershell
python -m pytest tests/ -q
```

Expected result: `48 passed`. This confirms the engine is complete and
working — the tests use a mock transport, not the real API, so this step
costs nothing and needs no key.

## 5. Try the deterministic offline mode

This uses the mechanical core only (no Claude reasoning yet, so the workout
will be simple/generic) — good for confirming the pipeline produces valid
output before spending any API credit:

```powershell
python -m engine.cli --mode power --zone Tempo --duration 50
```

## 6. Get an Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in
   (or create an account).
2. Click **"Get API key"** (or find **API Keys** in the console menu).
3. Click **Create Key**, give it a name (e.g. `cycling-engine`), and copy the
   value immediately — it starts with `sk-ant-...` and is shown **only once**.
4. Make sure the account has some credit (a few dollars covers extensive
   testing — each generation costs a few cents).

**Never share this key or paste it into a chat, prompt, or commit.** Treat it
like a password.

## 7. Save the key as an environment variable (Windows, permanent)

In PowerShell, replace `YOUR_KEY_HERE` with your real key and run:

```powershell
[System.Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'YOUR_KEY_HERE', 'User')
```

Close PowerShell completely and open a new window for the change to take
effect. Verify it saved (this only shows the key on your own screen — never
share this output):

```powershell
echo $env:ANTHROPIC_API_KEY
```

## 8. Generate your first real workout

```powershell
cd E:\Dev\github\cycling-workout-engine\workout_engine
python pedir.py "resistencia aerobica de 1 hora"
```

You should see: an interpretation confirmation, a short wait while Claude
reasons, and a complete workout in valid intervals.icu syntax — saved to a
`.md` file in the current folder.

## Troubleshooting

- **`python` not recognized** → Python isn't installed or isn't on PATH.
  Reinstall from python.org and check "Add Python to PATH" during setup.
- **`ModuleNotFoundError: No module named 'anthropic'`** → re-run step 3.
- **Empty output from `echo $env:ANTHROPIC_API_KEY`** → the variable didn't
  save, or you didn't open a *new* PowerShell window after setting it. Redo
  step 7.
- **API errors mentioning authentication** → the key may be invalid or the
  account may need credit added at console.anthropic.com.
