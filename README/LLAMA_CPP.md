# Runtime integrado con llama.cpp

Atalaya puede utilizar `llama-server.exe` como alternativa portable a Ollama.
No se incluyen binarios ni modelos en el repositorio: ambos deben obtenerse de
sus distribuidores oficiales, verificarse y respetar sus licencias.

## Selección del proveedor

Defina las variables antes de iniciar Atalaya:

```powershell
$env:ATALAYA_LLM_PROVIDER = "llama_cpp"
$env:ATALAYA_LLAMA_CPP_SERVER = "C:\ruta\llama.cpp\llama-server.exe"
$env:ATALAYA_LLAMA_CPP_MODEL = "C:\ruta\modelos\atalaya.gguf"
$env:ATALAYA_LLAMA_CPP_HOST = "http://127.0.0.1:11435" # opcional
python main.py doctor
python main.py gui
```

Valores admitidos para `ATALAYA_LLM_PROVIDER`:

- `auto` (predeterminado): usa llama.cpp si encuentra el ejecutable integrado y
  `models\atalaya.gguf`; en otro caso conserva Ollama.
- `llama_cpp`: exige el ejecutable, el modelo y un servidor validado.
- `ollama`: utiliza exclusivamente Ollama.

Atalaya inicia `llama-server` en loopback con contexto 8192 y embeddings
habilitados. Antes de confiar en un servidor comprueba `/health`, el puerto en
escucha, el PID, la ruta del ejecutable y el archivo GGUF de su línea de comando.
No habilita las herramientas internas ni MCP de llama.cpp: las únicas herramientas
disponibles siguen pasando por el harness de solo lectura de Atalaya.

## Compatibilidad necesaria del modelo

El modelo GGUF debe admitir chat, JSON estructurado y llamadas a herramientas.
Un modelo que solo complete texto no es suficiente para el Chat de Atalaya. La
calidad de embeddings de un modelo generativo también puede ser inferior a un
modelo dedicado; ejecute `python main.py rag eval` antes de distribuirlo.

## Crear una distribución portable

El empaquetador acepta un ZIP oficial de llama.cpp y un GGUF. Los dos hashes son
obligatorios:

```powershell
packaging\build.ps1 `
  -LlamaCppZip C:\paquetes\llama-win-cpu-x64.zip `
  -LlamaCppSha256 <sha256-del-zip> `
  -LlamaCppLicense C:\licencias\llama.cpp-MIT.txt `
  -ModeloGguf C:\modelos\modelo.gguf `
  -ModeloSha256 <sha256-del-gguf> `
  -ModeloLicense C:\licencias\modelo.txt
```

El ZIP debe contener `llama-server.exe` y sus DLL. El modelo se instala como
`models\atalaya.gguf`; no se descarga durante la ejecución. El empaquetador
copia ambas licencias a `THIRD_PARTY_LICENSES`. No
redistribuya pesos cuya licencia no lo permita.

## Limitaciones

- Un proceso de servidor carga un modelo principal; Ollama resulta más cómodo
  para alternar muchos modelos.
- El instalador aumenta al menos el tamaño del GGUF y de los backends incluidos.
- CPU, CUDA y Vulkan requieren paquetes diferentes; publique solo variantes que
  haya probado en hardware real.
- Atalaya no actualiza automáticamente el binario ni el modelo.
