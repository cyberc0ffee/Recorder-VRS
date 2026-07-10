$ErrorActionPreference = "Stop"

Push-Location frontend
try {
    npm install
    npm run dev
}
finally {
    Pop-Location
}

