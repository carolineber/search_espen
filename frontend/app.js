const chatEl = document.getElementById("chat");
const formEl = document.getElementById("chat-form");
const questionEl = document.getElementById("question");
const providerEl = document.getElementById("provider");
const quickQuestionsEl = document.querySelector(".quick-questions-list");
const sendButtonEl = document.querySelector(".send-btn");

function renderMarkdown(text) {
  if (!window.marked || !window.DOMPurify) {
    return null;
  }

  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  return DOMPurify.sanitize(marked.parse(text));
}

function extractActionIds(text) {
  const matches = text.match(/\bAE_[A-Z0-9]+\b/g) || [];
  return [...new Set(matches)];
}

async function fetchActionDetails(ids) {
  if (ids.length === 0) {
    return [];
  }

  const response = await fetch("/api/actions/details", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Falha ao carregar ações.");
  }

  return data.actions || [];
}

async function requestActionOrder(ids) {
  const response = await fetch("/api/actions/order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ids,
      provider: providerEl ? providerEl.value : "openai",
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Falha ao sugerir trilha.");
  }

  addMessage(data.answer, "bot", data.sources || []);
}

function createActionSelection(actions) {
  if (actions.length === 0) {
    return null;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "action-selection";

  const title = document.createElement("h3");
  title.className = "action-selection-title";
  title.textContent = "Escolha dentre as ações abaixo";
  wrapper.appendChild(title);

  const list = document.createElement("div");
  list.className = "action-selection-list";

  actions.forEach((action) => {
    const label = document.createElement("label");
    label.className = "action-option";
    label.dataset.objective = action.objective || "Objetivo não informado no cadastro.";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = action.id;

    const box = document.createElement("span");
    box.className = "action-checkbox";
    box.textContent = "[ ]";

    const text = document.createElement("span");
    text.className = "action-option-text";
    text.textContent = `${action.id}: ${action.title}`;

    checkbox.addEventListener("change", () => {
      box.textContent = checkbox.checked ? "[x]" : "[ ]";
    });

    label.appendChild(checkbox);
    label.appendChild(box);
    label.appendChild(text);
    list.appendChild(label);
  });

  const button = document.createElement("button");
  button.type = "button";
  button.className = "button action-order-btn";
  button.textContent = "Sugerir ordem de aplicação";

  button.addEventListener("click", async () => {
    const selectedIds = [...list.querySelectorAll("input:checked")].map(
      (input) => input.value
    );

    if (selectedIds.length === 0) {
      addMessage("Selecione pelo menos uma ação educativa para eu sugerir a trilha.", "bot");
      return;
    }

    button.disabled = true;
    button.textContent = "Gerando sugestão...";
    try {
      await requestActionOrder(selectedIds);
    } catch (error) {
      addMessage(`Erro: ${error.message}`, "bot");
    } finally {
      button.disabled = false;
      button.textContent = "Sugerir ordem de aplicação";
    }
  });

  wrapper.appendChild(list);
  wrapper.appendChild(button);
  return wrapper;
}

function showActionPickerMessage(messageEl, sources, selectionEl) {
  messageEl.textContent = "";

  const summary = document.createElement("p");
  summary.className = "action-picker-summary";
  summary.textContent =
    "Sugestões de ações do cadastro, priorizando objetivo, competências, eixo, público-alvo e tipologia.";
  messageEl.appendChild(summary);

  if (sources.length > 0) {
    const sourceEl = document.createElement("div");
    sourceEl.className = "sources";
    sourceEl.textContent = `Fontes: ${sources.join(", ")}`;
    messageEl.appendChild(sourceEl);
  }

  messageEl.appendChild(selectionEl);
}

async function loadConfig() {
  if (!providerEl) {
    return;
  }

  try {
    const response = await fetch("/api/config");
    if (!response.ok) {
      return;
    }

    const config = await response.json();
    if (config?.default_chat_provider) {
      providerEl.value = config.default_chat_provider;
    }
  } catch (error) {
    console.warn("Nao foi possivel carregar a configuracao.", error);
  }
}

function addMessage(text, role, sources = []) {
  const item = document.createElement("div");
  item.className = `message ${role}`;

  if (role === "bot") {
    const renderedMarkdown = renderMarkdown(text);
    if (renderedMarkdown) {
      item.innerHTML = renderedMarkdown;
    } else {
      item.textContent = text;
    }
  } else {
    item.textContent = text;
  }

  if (sources.length > 0) {
    const sourceEl = document.createElement("div");
    sourceEl.className = "sources";
    sourceEl.textContent = `Fontes: ${sources.join(", ")}`;
    item.appendChild(sourceEl);
  }

  chatEl.appendChild(item);
  chatEl.scrollTop = chatEl.scrollHeight;
  return item;
}

async function submitQuestion(rawQuestion) {
  const question = rawQuestion.trim();
  if (!question) {
    return;
  }

  if (sendButtonEl) {
    sendButtonEl.disabled = true;
  }

  addMessage(question, "user");
  questionEl.value = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        provider: providerEl ? providerEl.value : "openai",
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Falha no chat.");
    }

    const botMessage = addMessage(data.answer, "bot", data.sources || []);
    const actionIds = extractActionIds(data.answer);
    if (actionIds.length > 0) {
      try {
        const actions = await fetchActionDetails(actionIds);
        const selection = createActionSelection(actions);
        if (selection) {
          showActionPickerMessage(botMessage, data.sources || [], selection);
          chatEl.scrollTop = chatEl.scrollHeight;
        }
      } catch (error) {
        console.warn("Nao foi possivel carregar as ações selecionaveis.", error);
      }
    }
  } catch (error) {
    addMessage(`Erro: ${error.message}`, "bot");
  } finally {
    if (sendButtonEl) {
      sendButtonEl.disabled = false;
    }
  }
}

async function sendQuestion(event) {
  event.preventDefault();
  await submitQuestion(questionEl.value);
}

formEl.addEventListener("submit", sendQuestion);
questionEl.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }

  event.preventDefault();
  await submitQuestion(questionEl.value);
});

loadConfig();

if (quickQuestionsEl) {
  quickQuestionsEl.addEventListener("click", async (event) => {
    const button = event.target.closest(".quick-question-btn");
    if (!button) {
      return;
    }

    const question = button.dataset.question || "";
    questionEl.value = question;
    await submitQuestion(question);
    questionEl.focus();
  });
}
