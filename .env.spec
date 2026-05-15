POSTGRES_USER=your_postgres_user
POSTGRES_PASSWORD=your_postgres_password
POSTGRES_DB=your_database_name
POSTGRES_PORT=5432

API_PORT=8000
ENVIRONMENT=local
UI_APP_URL=http://localhost:3000

SECRET_SIGNING_KEY=replace_with_a_secure_random_value
SUPER_USER_CREDENTIALS=admin@example.com:replace_with_secure_password

# Optional: if unset, email delivery is disabled and send attempts are logged.
EMAIL_SERVER_CREDENTIAL=
EMAIL_SMTP_SERVER=

# Kubernetes client
# Path to kubeconfig file. If unset, tries in-cluster auth then ~/.kube/config.
K8S_KUBECONFIG_PATH=
K8S_NAMESPACE=agent-farm

# Agents
# Full image ref for agent pods, e.g. {REGISTRY_URL}/agentfarm-openclaw-base:{VERSION}
AGENT_IMAGE=
# Fernet key for encrypting Slack tokens at rest. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
AGENT_TOKEN_ENCRYPTION_KEY=
# Name of the k8s imagePullSecret for the agent container image registry.
# Example: registry-pull-secret
AGENT_IMAGE_PULL_SECRET=
# LiteLLM proxy URL used by the API for key generation. Example: http://localhost:4000 (local port-forward)
LITELLM_BASE_URL=
# LiteLLM proxy URL injected into agent pods as OPENAI_BASE_URL. Example: http://litellm:4000
AGENT_LITELLM_BASE_URL=
# Name of the k8s Secret containing LITELLM_MASTER_KEY. Defaults to "litellm".
LITELLM_SECRET_NAME=litellm
