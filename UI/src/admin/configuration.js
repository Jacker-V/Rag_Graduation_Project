export function createConfigurationFeature({ API_BASE, showToast }) {
  let currentConfig = {};

  async function loadConfiguration() {
    try {
      const response = await fetch(`${API_BASE}/config`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to load configuration');
      }

      const data = await response.json();
      if (data.success) {
        currentConfig = data.raw_config;
        populateConfigForm(data.raw_config, data.current_provider);
      }
    } catch (error) {
      console.error('Error loading configuration:', error);
      showToast('Failed to load configuration', 'error');
    }
  }

  function populateConfigForm(config, currentProvider) {
    const useGeminiCheckbox = document.getElementById('config-use-gemini');
    const switchLabel = document.getElementById('switch-label-gemini');
    const isGemini = config.USE_GEMINI?.toLowerCase() === 'true' || config.USE_GEMINI === '1';

    if (useGeminiCheckbox) {
      useGeminiCheckbox.checked = isGemini;
      useGeminiCheckbox.addEventListener('change', handleGeminiToggle);
    }
    if (switchLabel) {
      switchLabel.textContent = isGemini ? 'ON' : 'OFF';
    }

    const providerName = document.getElementById('current-provider-name');
    if (providerName) {
      const providerDisplay = {
        github: 'GitHub Models',
        gemini: 'Google Gemini',
        ollama: 'Ollama (Local)',
        openrouter: 'OpenRouter',
      };
      providerName.textContent = providerDisplay[currentProvider] || currentProvider;
    }

    const providerSelect = document.getElementById('config-llm-provider');
    if (providerSelect) {
      providerSelect.value = config.LLM_PROVIDER || 'github';
      providerSelect.addEventListener('change', handleProviderChange);
      showProviderConfig(config.LLM_PROVIDER || 'github');
    }

    document.getElementById('config-github-token').value = config.LLM_TOKEN || '';
    document.getElementById('config-github-model').value = config.LLM_MODEL || 'openai/gpt-4.1';
    document.getElementById('config-github-endpoint').value =
      config.LLM_ENDPOINT || 'https://models.github.ai/inference';

    document.getElementById('config-gemini-key').value = config.GEMINI_API_KEY || '';
    document.getElementById('config-gemini-model').value = config.GEMINI_MODEL || 'gemini-2.5-flash';

    document.getElementById('config-ollama-host').value = config.OLLAMA_HOST || 'http://localhost:11434';
    document.getElementById('config-ollama-model').value = config.OLLAMA_MODEL || 'qwen3:0.6b';

    document.getElementById('config-openrouter-key').value = config.OPENROUTER_API_KEY || '';

    document.getElementById('config-temperature')?.setAttribute('value', config.TEMPERATURE || '0.1');
    document.getElementById('config-max-tokens').value = config.MAX_TOKENS || '1000';
    document.getElementById('config-chunk-size').value = config.CHUNK_SIZE || '600';
    document.getElementById('config-chunk-overlap').value = config.CHUNK_OVERLAP || '50';
    document.getElementById('config-similarity-top-k').value = config.SIMILARITY_TOP_K || '3';
    document.getElementById('config-chat-history-limit').value = config.CHAT_HISTORY_LIMIT || '4';

    const debugCheckbox = document.getElementById('config-debug');
    if (debugCheckbox) {
      debugCheckbox.checked = config.DEBUG?.toLowerCase() === 'true';
    }

    const logLevelSelect = document.getElementById('config-log-level');
    if (logLevelSelect) {
      logLevelSelect.value = config.LOG_LEVEL || 'INFO';
    }
  }

  function handleGeminiToggle(e) {
    const isEnabled = e.target.checked;
    const switchLabel = document.getElementById('switch-label-gemini');
    const providerName = document.getElementById('current-provider-name');

    if (switchLabel) {
      switchLabel.textContent = isEnabled ? 'ON' : 'OFF';
    }

    if (providerName) {
      providerName.textContent = isEnabled ? 'Google Gemini' : 'GitHub Models';
    }

    const providerSelect = document.getElementById('config-llm-provider');
    if (providerSelect && isEnabled) {
      providerSelect.value = 'gemini';
      showProviderConfig('gemini');
    } else if (providerSelect && !isEnabled) {
      providerSelect.value = 'github';
      showProviderConfig('github');
    }
  }

  function handleProviderChange(e) {
    const provider = e.target.value;
    showProviderConfig(provider);

    const useGeminiCheckbox = document.getElementById('config-use-gemini');
    const switchLabel = document.getElementById('switch-label-gemini');
    const providerName = document.getElementById('current-provider-name');

    const isGemini = provider === 'gemini';

    if (useGeminiCheckbox) {
      useGeminiCheckbox.checked = isGemini;
    }
    if (switchLabel) {
      switchLabel.textContent = isGemini ? 'ON' : 'OFF';
    }
    if (providerName) {
      const providerDisplay = {
        github: 'GitHub Models',
        gemini: 'Google Gemini',
        ollama: 'Ollama (Local)',
        openrouter: 'OpenRouter',
      };
      providerName.textContent = providerDisplay[provider] || provider;
    }
  }

  function showProviderConfig(provider) {
    document.querySelectorAll('.provider-config').forEach((el) => {
      el.style.display = 'none';
    });

    const configId = `${provider}-config`;
    const configEl = document.getElementById(configId);
    if (configEl) {
      configEl.style.display = 'block';
    }
  }

  function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    const icon = input?.nextElementSibling?.querySelector('i');

    if (input) {
      if (input.type === 'password') {
        input.type = 'text';
        if (icon) icon.className = 'fas fa-eye-slash';
      } else {
        input.type = 'password';
        if (icon) icon.className = 'fas fa-eye';
      }
    }
  }

  function gatherConfigFromForm() {
    const useGemini = document.getElementById('config-use-gemini')?.checked;
    const provider = document.getElementById('config-llm-provider')?.value;

    return {
      USE_GEMINI: useGemini ? 'true' : 'false',
      LLM_PROVIDER: provider,

      LLM_TOKEN: document.getElementById('config-github-token')?.value || '',
      LLM_MODEL: document.getElementById('config-github-model')?.value || 'openai/gpt-4.1',
      LLM_ENDPOINT:
        document.getElementById('config-github-endpoint')?.value || 'https://models.github.ai/inference',

      GEMINI_API_KEY: document.getElementById('config-gemini-key')?.value || '',
      GEMINI_MODEL: document.getElementById('config-gemini-model')?.value || 'gemini-2.5-flash',

      OLLAMA_HOST: document.getElementById('config-ollama-host')?.value || 'http://localhost:11434',
      OLLAMA_MODEL: document.getElementById('config-ollama-model')?.value || 'qwen3:0.6b',

      OPENROUTER_API_KEY: document.getElementById('config-openrouter-key')?.value || '',

      MAX_TOKENS: document.getElementById('config-max-tokens')?.value || '1000',
      CHUNK_SIZE: document.getElementById('config-chunk-size')?.value || '600',
      CHUNK_OVERLAP: document.getElementById('config-chunk-overlap')?.value || '50',
      SIMILARITY_TOP_K: document.getElementById('config-similarity-top-k')?.value || '3',
      CHAT_HISTORY_LIMIT: document.getElementById('config-chat-history-limit')?.value || '4',

      DEBUG: document.getElementById('config-debug')?.checked ? 'True' : 'False',
      LOG_LEVEL: document.getElementById('config-log-level')?.value || 'INFO',
    };
  }

  async function saveConfiguration() {
    try {
      const config = gatherConfigFromForm();

      const response = await fetch(`${API_BASE}/config`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(config),
      });

      const data = await response.json();

      if (data.success) {
        showToast('Configuration saved successfully!', 'success');
        currentConfig = { ...currentConfig, ...config };
      } else {
        throw new Error(data.error || 'Failed to save configuration');
      }
    } catch (error) {
      console.error('Error saving configuration:', error);
      showToast(`Error: ${error.message}`, 'error');
    }
  }

  function checkServerAndReload(attempts = 0) {
    if (attempts > 10) {
      showToast('Server may still be restarting. Please refresh manually.', 'warning');
      return;
    }

    fetch(`${API_BASE}/auth/validate`, { credentials: 'include' })
      .then((response) => {
        if (response.ok) {
          window.location.reload();
        } else {
          setTimeout(() => checkServerAndReload(attempts + 1), 2000);
        }
      })
      .catch(() => {
        setTimeout(() => checkServerAndReload(attempts + 1), 2000);
      });
  }

  async function restartServer() {
    if (!confirm('Are you sure you want to restart the server? The page will reload automatically.')) {
      return;
    }

    try {
      await saveConfiguration();

      showToast('Server is restarting...', 'info');

      await fetch(`${API_BASE}/config/restart`, {
        method: 'POST',
        credentials: 'include',
      });

      setTimeout(() => {
        showToast('Attempting to reconnect...', 'info');
        checkServerAndReload();
      }, 3000);
    } catch (error) {
      console.error('Error restarting server:', error);
      showToast('Server restart initiated. Please refresh manually.', 'warning');
    }
  }

  async function testLLMConnection() {
    const provider = document.getElementById('config-llm-provider')?.value;
    const testData = { provider };

    if (provider === 'github') {
      testData.token = document.getElementById('config-github-token')?.value;
      testData.model = document.getElementById('config-github-model')?.value;
      testData.endpoint = document.getElementById('config-github-endpoint')?.value;
    } else if (provider === 'gemini') {
      testData.api_key = document.getElementById('config-gemini-key')?.value;
      testData.model = document.getElementById('config-gemini-model')?.value;
    }

    try {
      showToast('Testing connection...', 'info');

      const response = await fetch(`${API_BASE}/config/test-llm`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(testData),
      });

      const data = await response.json();

      if (data.success) {
        showToast(`✓ ${data.message}`, 'success');
      } else {
        throw new Error(data.error || 'Connection test failed');
      }
    } catch (error) {
      console.error('LLM test error:', error);
      showToast(`✗ Error: ${error.message}`, 'error');
    }
  }

  return {
    loadConfiguration,
    saveConfiguration,
    restartServer,
    testLLMConnection,
    togglePassword,
  };
}
