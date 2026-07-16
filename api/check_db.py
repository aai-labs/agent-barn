from sqlmodel import Session, select
from api.core.config import get_config
from sqlalchemy import create_engine
from api.domains.organizations.models import Organization
import json

engine = create_engine(str(get_config().db_connection_url))
with Session(engine) as session:
    orgs = session.exec(select(Organization)).all()
    for org in orgs:
        print(f"Organization: {org.name}")
        print(f"  - allowed_models: {json.dumps(org.allowed_models)}")
        print("-" * 40)
