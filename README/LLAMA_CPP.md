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
$env:ATALAYA_LLAMA_CPP_EMBEDDING_MODEL = "C:\ruta\modelos\embedding.gguf" # opcional
$env:ATALAYA_LLAMA_CPP_EMBEDDING_HOST = "http://127.0.0.1:11436" # opcional
python main.py doctor
python main.py gui
```

Valores admitidos para `ATALAYA_LLM_PROVIDER`:

- `auto` (predeterminado): usa llama.cpp si encuentra el ejecutable integrado y
  `models\atalaya.gguf`; en otro caso conserva Ollama.
- `llama_cpp`: exige el ejecutable, el modelo y un servidor validado.
- `ollama`: utiliza exclusivamente Ollama.
- `none`: mantiene recolección, reglas y alertas sin iniciar ninguna IA.

La página **Sistema > IA local** permite autorizar un
`llama-server.exe` y archivos GGUF sin usar variables de entorno. Atalaya no
escanea el disco: el usuario proporciona cada ruta, elige las funciones
permitidas y confirma su asignación. Antes de registrar se valida la cabecera,
se calcula SHA-256 y, antes de cada arranque, se vuelve a comprobar que el
ejecutable y el modelo no hayan cambiado. Encontrar o registrar un archivo no
lo ejecuta; la prueba de compatibilidad requiere pulsar el botón correspondiente.

Atalaya usa dos procesos separados: chat/análisis en `11435` y, si existe un
modelo dedicado, embeddings en `11436`. Solo el segundo recibe `--embedding`;
esa opción restringe el servidor y no debe usarse en el proceso de chat. Ambos
usan una clave API aleatoria guardada en la carpeta local de datos y arrancan
con la interfaz web deshabilitada. Antes de confiar en un servidor comprueba
`/health`, el puerto en
escucha, el PID, la ruta del ejecutable y el archivo GGUF de su línea de comando.
No habilita las herramientas internas ni MCP de llama.cpp: las únicas herramientas
disponibles siguen pasando por el harness de solo lectura de Atalaya.

Si uno de los puertos configurados ya está ocupado por otro programa, Atalaya
selecciona un puerto libre de loopback para esa sesión y dirige allí todos sus
clientes. Nunca reutiliza un servicio solo porque responda en el puerto.

Los paquetes construidos con llama.cpp incluyen `COMPONENTS.sha256.json`.
Antes de arrancar, Atalaya verifica contra él `llama-server.exe` y el modelo
correspondiente; una alteración bloquea su ejecución. El manifiesto detecta
corrupción o cambios posteriores al empaquetado. Para autenticar también al
distribuidor, firme el instalador con un certificado de firma de código.

En Windows, Atalaya intenta incorporar cada servidor iniciado a un Job Object
con `KILL_ON_JOB_CLOSE`: cuando el sistema permite la asignación, si Atalaya
termina abruptamente Windows finaliza también el proceso de IA y evita
servidores huérfanos. La salida normal conserva además el cierre explícito.

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
  -ModeloLicense C:\licencias\modelo.txt `
  -EmbeddingGguf C:\modelos\embedding.gguf `
  -EmbeddingSha256 <sha256-del-embedding> `
  -EmbeddingLicense C:\licencias\embedding.txt
```

El ZIP debe contener `llama-server.exe` y sus DLL. El modelo se instala como
`models\atalaya.gguf`; no se descarga durante la ejecución. El empaquetador
copia las licencias a `THIRD_PARTY_LICENSES`. El modelo de embeddings es
opcional; sin él, el RAG mantiene la búsqueda léxica. No
redistribuya pesos cuya licencia no lo permita.

## Limitaciones

- Un proceso de servidor carga un modelo principal; Ollama resulta más cómodo
  para alternar muchos modelos.
- El instalador aumenta al menos el tamaño del GGUF y de los backends incluidos.
- CPU, CUDA y Vulkan requieren paquetes diferentes; publique solo variantes que
  haya probado en hardware real.
- Atalaya no actualiza automáticamente el binario ni el modelo.
