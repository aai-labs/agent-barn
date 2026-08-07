from api.domains.templates.predefined.loader import PredefinedTemplate, load_predefined_templates

PREDEFINED_TEMPLATES: tuple[PredefinedTemplate, ...] = load_predefined_templates()

__all__ = ["PREDEFINED_TEMPLATES", "PredefinedTemplate"]
