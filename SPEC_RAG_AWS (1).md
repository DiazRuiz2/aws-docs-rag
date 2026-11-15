# Especificación de implementación — RAG local para documentación AWS

**Estado:** listo para iniciar implementación  
**Versión:** 1.1 · 12 de noviembre de 2026  
**Destinatario:** agente de desarrollo (Codex u otro)  
**Idioma de la aplicación y las consultas:** inglés. Este documento está en español para facilitar la revisión.

## 1. Objetivo

Construir un **RAG local, sencillo, reproducible y evaluable** que responda preguntas técnicas **en inglés** utilizando exclusivamente la documentación AWS disponible en el repositorio. Existe una carpeta `data/` con distintos elementos y es posible que los archivos normalizados sean **JSON**, pero **su contenido, formato y finalidad no están verificados**. El agente deberá descubrirlos antes de diseñar la ingestión.

**Principio rector:** primero implementar y medir un RAG básico; añadir técnicas avanzadas solo si los errores observados y la evaluación justifican su complejidad.

## 2. Decisiones cerradas

| Área | Especificación |
|---|---|
| Fuente | **Carpeta `data/` existente, con estructura y formatos por verificar**. No asumir `.md`, `.json` ni un esquema concreto; no hacer scraping ni descargas automáticas |
| Idioma | Inglés (documentos, consultas y respuestas) |
| Lenguaje | Python **3.10** |
| Framework | **LangChain** |
| Gestión del proyecto | **uv**, `pyproject.toml`, `uv.lock`, `.python-version` |
| Base vectorial | **Chroma local**, persistida en disco |
| Embeddings iniciales | **BAAI/bge-small-en-v1.5** (modelo candidato, sustituible mediante configuración) |
| Generación | LLM pequeño y abierto, servido localmente mediante **Ollama**; candidato inicial: **Qwen3 1.7B**, si el equipo puede ejecutarlo |
| Interfaz | **CLI**, sin frontend, API ni despliegue cloud en la primera versión |
| Retrieval inicial | **Dense vector search**, top-k configurable (valor inicial: 4) |
| Chunking inicial | Basado en el **texto documental realmente extraído** tras verificar formatos, estructura y unidades documentales; no predeterminar tamaños |
| Persistencia | Reutilizar índice y embeddings entre ejecuciones; mantener los artefactos generados **fuera de `data/`**, en `.rag_state/` |
| Evidencia | Mostrar rutas y localizadores existentes (sección, ID, clave o posición JSON, si procede); admitir abstención y no inventar metadatos |
| Evaluación | Preguntas y referencias derivadas **únicamente** del contenido documental realmente identificado como válido |

**No son requisitos de la primera versión:** Parent-Child, BM25, búsqueda híbrida 70/30, RRF, reranking, agentes, LangGraph, query rewriting, observabilidad SaaS, servicios gestionados o UI web.

## 3. Fases de trabajo

### Fase 0. Exploración de `data/` y descubrimiento del corpus — obligatoria, antes de diseñar la ingestión

**Regla no negociable:** **no asumir nada que pueda comprobarse inspeccionando el repositorio o los archivos**. La afirmación de que la normalización está en JSON es una pista del usuario, no un hecho verificado. El agente debe determinar qué existe y cómo se relacionan sus elementos.

1. **Inventariar recursivamente `data/` en modo lectura:** estructura, tipos/extensiones, tamaños, cantidades, nombres y relaciones aparentes. Detectar también archivos sin extensión, JSON, JSONL/NDJSON, Markdown, texto, binarios, índices, cachés, metadatos y posibles salidas de procesos anteriores. No confiar únicamente en las extensiones.
2. **Identificar la función real de cada elemento o grupo:** datos fuente, documentación normalizada, metadatos, índices, archivos intermedios, duplicados, cachés u otros. Basar las clasificaciones en evidencia observable, no en nombres de carpetas. Registrar lo desconocido como desconocido.
3. **Validar formatos y esquemas sobre muestras representativas**, sin modificar archivos. Para JSON: distinguir objeto único, array, registros anidados o JSONL; revisar claves y tipos, campos de texto, título, jerarquía, identificadores, enlaces, procedencia y metadatos. Comprobar codificación, archivos vacíos o corruptos y heterogeneidad entre archivos. No asumir que el texto documental está en una clave llamada `content` o `text`.
4. **Reconstruir la unidad documental real:** determinar qué registros contienen información consultable, cómo extraer el texto sin perder contexto, cómo identificar cada unidad de forma estable y cómo citar su procedencia (ruta + identificador o posición del registro; encabezados solo si existen). Excluir del índice índices, configuraciones, cachés y cualquier elemento sin contenido documental justificable. No indexar indiscriminadamente todo `data/`.
5. **Caracterizar el corpus efectivamente utilizable:** número de documentos/registros, tamaños, longitud aproximada en tokens, secciones si existen, bloques de código, tablas, comandos, duplicados, calidad y distribución del contenido. Diferenciar el tamaño de la carpeta del tamaño del corpus útil.
6. **Decidir el loader/normalizador y el chunking después del análisis:** elegir y documentar la extracción apropiada a los formatos observados; aprovechar la estructura semántica existente (secciones, títulos, registros) y subdividir solo donde haga falta. Justificar tamaños, overlap y reglas de corte; no imponer Parent-Child ni forzar una conversión a Markdown.
7. **Dejar constancia de incertidumbres y límites:** si un formato, campo o relación es ambiguo, indicarlo y adoptar una decisión conservadora documentada; si no se puede identificar con suficiente confianza el corpus, no indexar material arbitrario. No inventar esquemas, campos, rutas, URLs ni transformaciones para ocultar errores.

**Entregable obligatorio:** `reports/corpus_analysis.md`, con inventario por tipo/función, evidencia de muestras examinadas, esquema(s) constatados, criterios de selección/exclusión, estrategia de extracción/chunking, ejemplos reales de procedencia y cuestiones sin resolver. **Completar esta fase antes de programar loaders específicos.**

### Fase 1. MVP funcional — imprescindible

**Ingestión**

- Leer **solo las unidades documentales verificadas** en la fase 0, utilizando los loaders/parsers adecuados a los formatos **realmente presentes**. Conservar íntegros todos los archivos fuente y sus estructuras originales; si se requiere un formato intermedio, generarlo separadamente y de forma reversible o trazable.
- Crear chunks respetando los límites semánticos detectados, las unidades lógicas de código/tablas y los límites entre documentos o registros; no mezclar registros sin justificación.
- Guardar metadatos por chunk **cuando puedan obtenerse o generarse de forma trazable**: `source_path`, `doc_id`, `chunk_id`, `source_locator` (por ejemplo, índice de array, JSON Pointer o ID original), `file_hash`; `heading_path` y URL original solo si existen. Mantener correspondencia verificable entre chunk y fragmento fuente.
- Generar embeddings con un modelo local inglés y persistirlos en Chroma.
- Evitar duplicados y soportar nuevas ingestas: archivos o registros nuevos, modificados o eliminados. Comparar hashes de contenido y eliminar/actualizar sus chunks cuando corresponda; no borrar registros ajenos al corpus validado.
- Guardar un manifiesto local con identidad de fuentes y registros, hashes, versión de parser/extracción, versión de embedding y versión de chunking. Si cambia la interpretación del JSON, el modelo o la segmentación, invalidar/reconstruir lo necesario.

**Consulta**

1. Recibir una pregunta en inglés.
2. Recuperar los `k` chunks más relevantes desde Chroma (vector search).
3. Preparar un contexto con un límite de tokens, eliminando duplicados.
4. Pedir al LLM que responda **solo con información de los fragmentos recuperados**; cuando no haya evidencia suficiente, responder que no consta en la documentación suministrada.
5. Devolver una respuesta breve con referencias **verificables** a archivo y, según el formato real, sección, identificador de registro o posición JSON; no fabricar encabezados, URLs ni atribuciones.

**Configuración y persistencia**

- **No reutilizar ni modificar `data/` como directorio de salida**: su contenido preexistente pertenece al corpus pendiente de inspección. Almacenar Chroma en `.rag_state/chroma/` y el manifiesto en `.rag_state/index_manifest.json` por defecto. Si se descubren índices previos en `data/`, clasificarlos, pero no sobrescribirlos.
- Mantener modelos, rutas, `top_k`, presupuesto de contexto, temperatura y host de Ollama configurables en un único lugar (`.env` y/o archivo de configuración con valores por defecto).
- Ignorar en Git `.rag_state/` y otros artefactos generados, **sin excluir `data/` de forma global ni alterar su seguimiento**; respetar las políticas existentes del repositorio.
- No recalcular embeddings en cada consulta ni reindexar documentos sin cambios.

**CLI requerida**

```bash
uv sync
uv run python -m aws_rag inspect --source-dir data
uv run python -m aws_rag ingest --source-dir data
uv run python -m aws_rag ask "How does S3 versioning work?"
uv run python -m aws_rag evaluate
uv run python -m aws_rag ingest --source-dir data --force
```

Los comandos pueden implementarse con `argparse` (sin añadir dependencias innecesarias). La pregunta de ejemplo es solo ilustrativa: el corpus podría no cubrir S3.

### Fase 2. Evaluación — imprescindible

**Preparación del conjunto de pruebas**

- Inspeccionar el corpus **realmente identificado como documentación** y crear consultas **en inglés** a partir de hechos verificables en sus registros o archivos.
- Como punto de partida: distribuir preguntas entre las **unidades documentales útiles** (no necesariamente un archivo = un documento), ajustando el total al tamaño y diversidad reales del corpus (orientativamente 15–40 cuando haya material suficiente). Evitar duplicados o preguntas artificiales.
- Para cada pregunta registrar: `question`, `answerable`, `reference_source_path`, `reference_locator` (ID/posición JSON/sección existente), `reference_excerpt` y, opcionalmente, respuesta esperada. No crear encabezados ficticios para registros JSON.
- Incluir unas pocas preguntas **sin respuesta** en el corpus para probar la abstención.
- Si un LLM propone preguntas, **contrastar cada pregunta, respuesta y referencia** contra el contenido existente, con verificaciones reproducibles y revisión de una muestra representativa. La salida sintética no constituye por sí sola la verdad de referencia; no fingir una revisión humana que no se haya realizado.
- Reservar, cuando la cantidad lo permita, un pequeño subconjunto de preguntas para la comprobación final sin ajustar parámetros sobre él.

**Métricas mínimas**

- **Recall@K** de la sección/documento relevante recuperado.
- **MRR@K** de recuperación.
- Revisión de **exactitud y fundamentación** de las respuestas frente a los extractos fuente.
- **Tasa de abstención correcta** en preguntas fuera de cobertura.
- **Latencia** de consulta (retrieval y generación, por separado si es posible).

**Entregables:** `evaluation/questions.jsonl` y `reports/evaluation_baseline.md` con resultados, ejemplos de errores y recomendaciones concretas.

### Fase 3. Mejoras opcionales — solo si la evaluación las justifica

Evaluar **una modificación cada vez**, comparándola con el baseline bajo las mismas preguntas, modelo, `top_k` y hardware. Registrar métricas, coste de mantenimiento y latencia.

**Experimento A: BM25 / Hybrid Search**
- **Problema que debe demostrar el corpus:** fallos con nombres exactos de servicios, parámetros, comandos, identificadores o códigos de error.
- Implementar BM25 sobre los mismos chunks; combinar los rankings con **Weighted Reciprocal Rank Fusion** (70% vector / 30% BM25 como **hipótesis**, no valor obligatorio).
- Si el BM25 es pequeño, puede reconstruirse al iniciar a partir de los chunks guardados. No asumir que Chroma local proporciona el mismo pipeline híbrido que otros despliegues.
- Retener la mejora solo si produce resultados relevantes mejores sin penalización desproporcionada de latencia o complejidad.

**Experimento B: Parent-Child Retrieval**
- **Problema que debe demostrar el corpus:** chunks que contienen términos relevantes pero carecen del contexto necesario para responder.
- Indexar children para recuperar por similitud; recuperar parents desde un almacén local persistente mediante IDs estables.
- Comparar con chunking convencional, manteniendo controlado el presupuesto total de contexto.
- Si se combina con Hybrid Search, fusionar primero resultados de **children**, deduplicarlos y después resolver los **parents**.
- Retener la mejora solo si supera el baseline en las métricas relevantes.

No introducir rerankers ni estrategias adicionales sin un problema específico medido.

## 4. Estructura objetivo del repositorio

```text
aws-docs-rag/
├── data/                        # Carpeta existente: explorar; contenido y finalidad por verificar; NO modificar
├── src/
│   └── aws_rag/
│       ├── __init__.py
│       ├── __main__.py          # CLI
│       ├── config.py
│       ├── corpus.py            # Inventario, validación, selección y extracción basada en formatos reales
│       ├── chunking.py          # Estrategia derivada del contenido extraído
│       ├── indexing.py         # Embeddings + Chroma + manifiesto
│       ├── retrieval.py        # Dense retrieval; ampliable
│       ├── generation.py       # LLM + prompt + referencias
│       └── evaluation.py       # Métricas / informe
├── tests/
├── evaluation/
│   └── questions.jsonl
├── reports/
│   ├── corpus_analysis.md
│   └── evaluation_baseline.md
├── .rag_state/                  # Persistencia generada (gitignored; separada de data/)
├── .env.example
├── .gitignore
├── .python-version
├── pyproject.toml
├── uv.lock
└── README.md
```

La estructura es orientativa: mantener separación de responsabilidades, pero no crear abstracciones prematuras.

## 5. Requisitos de calidad y límites

- Ejecutar **sin claves de API comerciales**; los modelos y Chroma corren localmente.
- Utilizar paquetes de integración actuales compatibles con **Python 3.10** y fijar sus versiones reales en `uv.lock`.
- Encapsular el proveedor de embeddings y el LLM para poder cambiar de modelo mediante configuración, **sin** construir un sistema de plugins genérico.
- Temperatura baja para respuestas técnicas; sin memoria conversacional, agentes ni herramientas de navegación en v1.
- Las respuestas deben distinguir entre evidencia hallada y ausencia de documentación.
- Implementar pruebas de parsers para esquemas realmente observados, ingestión, conservación de metadatos y localizadores, actualización incremental, selección de chunks, referencias y abstención.
- Facilitar mensajes de error comprensibles si falta Ollama, el modelo local o un índice válido.
- Documentar comandos exactos de instalación, descarga del modelo, indexación, consulta y evaluación.
- No modificar, eliminar ni reorganizar nada de `data/`. No generar documentación AWS inexistente ni asumir campos, estructura o semántica sin verificarlos.

## 6. Criterios de aceptación del MVP

El proyecto se considera implementado cuando:

1. `uv sync` instala las dependencias y la CLI funciona con Python 3.10.
2. `inspect` inventaría `data/`, distingue material documental de otros artefactos, verifica formatos/esquemas reales y justifica la extracción y el chunking elegidos.
3. `ingest` indexa todas las **unidades documentales elegibles y verificadas** del corpus —sean JSON, Markdown u otro formato compatible constatado—, con localizadores verificables, metadatos y persistencia fuera de `data/`.
4. Ejecutar de nuevo `ingest` sin cambios **no recalcula** los embeddings; añadir, editar o borrar archivos actualiza el índice correctamente.
5. `ask` responde desde los archivos proporcionados, cita rutas y localizadores realmente existentes y se abstiene cuando falta evidencia.
6. `evaluate` produce un informe reproducible con métricas de recuperación, fundamentación y latencia, además de ejemplos de fallos.
7. Existe un `README.md` con instrucciones verificadas y pruebas automatizadas básicas que pasan.
8. No se han introducido Hybrid Search ni Parent-Child sin evidencia cuantitativa de que resultan útiles.

**Importante:** no fijar objetivos numéricos arbitrarios antes de conocer el corpus. El informe de evaluación deberá indicar si los resultados del baseline son suficientemente buenos y qué limitaciones persisten.

## 7. Orden de ejecución para el agente

1. Comprobar la estructura del repositorio y **explorar recursivamente `data/` en modo solo lectura**, sin asumir su estructura, formato ni función.
2. Determinar con evidencia cuáles son las fuentes documentales utilizables, sus esquemas y el modo correcto de extraerlas. Registrar los hallazgos en `reports/corpus_analysis.md`.
3. Elegir y justificar parsers, unidad documental, chunking y parámetros **a partir de los resultados constatados**.
4. Implementar MVP denso con LangChain, Chroma, Ollama y CLI.
5. Crear y verificar el conjunto de evaluación basado exclusivamente en los documentos.
6. Ejecutar pruebas y evaluación; documentar resultados.
7. Identificar fallos. Proponer, **sin añadir automáticamente**, BM25/Hybrid o Parent-Child solo si la evidencia los respalda.
8. Entregar el repositorio funcional y un resumen de decisiones, pruebas y limitaciones.

**Instrucción final al agente:** **primero explorar y demostrar, después decidir e implementar**. No asumir que el contenido es JSON, Markdown, que tiene un campo de texto específico, ni que todos los elementos de `data/` deben indexarse. No alterar ningún archivo preexistente de `data/`; registrar la evidencia y las incertidumbres. Priorizar una implementación pequeña, clara y robusta. No confundir sofisticación arquitectónica con calidad de recuperación; justificar cualquier complejidad adicional mediante una comparación reproducible.
