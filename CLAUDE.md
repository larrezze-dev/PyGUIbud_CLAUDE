## Proyecto PyGUIbud
Crear una aplicación para generar GUI's para Python en TTKBootstrap y si posible PYSide drag-and-drop, concepto similar a PyQt pero generando archivos .ui que solo dependan de tkinter y/o ttkboostrapt/pyside

En primer paso es determinar el stack, que tiene que ser el mas flexible a la vez que lo mas adaptable, pensado para un proyecto open source con forks aceptables por el creador.

Como propuesta crear um .md compacto (resumido) y un (o mas) proyecto conceptual en formato mermaid renderizable dentro del project.md de la aplicación.

Crear el concepto del proyecto dentro de:
D:\Coding\SAPE\PyGUIbud

Como referencia de UI puedes copiar (nunca referenciar, borrar, editar o borrar) los archivos guardados en:
G:\Mi unidad\Trabalho\Sape\UI-Design\corporate-identity\03-corporate-image

En primer paso es determinar el stack, que tiene que ser el mas flexible a la vez que lo mas adaptable, pensado para un proyecto open source con forks aceptables por el creador.

Paso 1: determinar el AI Agent para cada sub-agent o tarea
Paso 3: determinar el tipo de licencia (AI Ageng)
Paso 3: determinar las características técnicas (a través de conversaciones con el AI Agent)

## Agentes
- ORCHESTRATOR: el agente por defecto y que usa el modelo de AI seleccionado por el usuario. Delega tareas a los sub-agents que pertocan y se comunica directamente con ellos. Es el único agente que reporta al usuario. Crear/buscar el skill para crear este agent.
- SOFTWARE-ARCHITECHT: el agente que coordinado por ORCHESTRATOR. Especializado en desarrollo de software. Crear/buscar el skill para crear este agent.
- BACKEND-DEVELOPER: el nombre lo dice.  Crear/buscar el skill para crear este agent. No malgastar tokens, ni ahorrarlos al punto de sacrificar calidad. Decidir el modelo en función de las tareas delegadas (para cada tarea un modelo ponderado)
- FRONTEND-DEVELOPER: el nombre lo dice. crear/obtener skill. No malgastar tokens, ni ahorrarlos al punto de sacrificar calidad. Decidir el modelo en función de las tareas delegadas (para cada tarea un modelo ponderado)
- DEBUGGER: crear/obtener skill. No escatimar recursos
- TESTING:  crear/obtener skill. Usar todas las herramientas disponibles, incluso tomar control del ordenador.
- QA:  crear/obtener skill. Una vez no hayan bugs, realizar todas las pruebas posibles. Verificar que sea un software a prueba de idiotas - no que sea tan self-explaining, pero que si un idiota intenta hacer una idiotez, queda bloqueada la acción. Un Quality Assistan en toda regla. Usar todas las herramientas disponibles, incluso tomar control del ordenador.
- SCORER: vigila el desarrollo de la aplicación y permite un seguimiento activo, visual por parte del desarrollador.
- DEPLOYER: se tiene que desplegar de forma que sea compatible con pip y uv (el último si posible).
- EL LAME-CULOS: una vez completado el proyecto, lo hará visible al mundo.

## Ventana de contexto
Create a realistic development plan, sane into de project on the place and name you prefer. Shall be created that each step can be started and finished in one chat, lefting behind the instructions for the next chat/session to follow up. Don't wait until de token window is over 70% to advise a new session is necessary. Watch all the time the window context to avoid not necessary compression.

### 1.1 Context Threshold Rule (Strict < 70% Limit)
- **Active Monitoring:** The agent and developer must monitor context token utilisation continuously.
- **Pre-emptive Stop at 60–65%:** If conversation context reaches **60–65%** of the window capacity, the active session **must immediately enter wrap-up mode**. Never wait until or beyond 70%.
- **Atomic Boundary:** No new feature implementation may begin once the session crosses the 55% mark if that feature cannot be fully coded, tested, and documented within 5%.
- **Wrap-up Routine:** When triggering a session transition:
  1. Complete and commit/save the immediate atomic file edit.
  2. Run the test suite (`pytest`) to confirm green baseline.
  3. Emit the **Standard Session Handover Block** (defined in [Section 1.2](app://obsidian.md/index.html#12-standard-session-handover-format)).
  4. Explicitly instruct the user to start a new chat session.

### 1.2 Standard Session Handover Format
At the conclusion of every chat session (or upon reaching 60–65% context limit), the agent must output:

```markdown
### 📋 Session Handover Briefing
- **Step Completed:** [e.g., Step 03: XML Parser & Serialiser]
- **Deliverables Created/Modified:**
  - `pyguibud/core/xml_io.py`
  - `tests/test_xml_io.py`
- **Verification Status:** `pytest tests/test_xml_io.py` -> 12 passed in 0.18s
- **Current Git / Working State:** Clean, all tests passing.
- **Next Step to Execute:** [e.g., Step 04: Python Code Generator (`pyguibud.core.codegen`)]

#### 🚀 Next Session Kickoff Prompt
> Copy and paste the following snippet into the new chat to resume seamlessly:
> *"Resume PyGUIbud development at Step 04: Python Code Generator (`pyguibud.core.codegen`). Inspect [DEVELOPMENT_PLAN.md](file:./DEVELOPMENT_PLAN.md) and [project.md](file:./project.md). Verify current state with `pytest` before starting."*