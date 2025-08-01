"""change_id_fields_to_bigint_v2

Revision ID: 02fb47ee65c1
Revises: add_asset_snapshots
Create Date: 2025-08-01 01:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02fb47ee65c1'
down_revision: Union[str, None] = 'add_asset_snapshots'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Change all ID fields from Integer to BigInteger to support autoincrement
    
    # Get the database connection to check the dialect
    connection = op.get_bind()
    is_mysql = connection.dialect.name == 'mysql'
    
    if is_mysql:
        # MySQL approach - use ALTER COLUMN
        # First, drop all foreign key constraints that might cause issues
        try:
            op.drop_constraint('execution_orders_ibfk_1', 'execution_orders', type_='foreignkey')
        except Exception:
            pass
        
        try:
            op.drop_constraint('fk_execution_orders_project_id', 'execution_orders', type_='foreignkey')
        except Exception:
            pass
        
        # Change column types for MySQL
        op.alter_column('users', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('roles', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('projects', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('project_configs', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('datasources', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('executors', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('strategies', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('positions', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('orders', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('signals', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        op.alter_column('asset_snapshots', 'id', type_=sa.BigInteger(), nullable=False, autoincrement=True, existing_type=sa.Integer())
        
        # Foreign key and reference ID changes
        op.alter_column('projects', 'created_by', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('project_configs', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('datasources', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('executors', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('strategies', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('positions', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('positions', 'strategy_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('orders', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('orders', 'position_id', type_=sa.BigInteger(), nullable=True, existing_type=sa.Integer())
        op.alter_column('orders', 'exec_order_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('orders', 'signal_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('orders', 'strategy_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('orders', 'executor_id', type_=sa.BigInteger(), nullable=True, existing_type=sa.Integer())
        op.alter_column('signals', 'project_id', type_=sa.BigInteger(), nullable=True, existing_type=sa.Integer())
        op.alter_column('signals', 'strategy_id', type_=sa.BigInteger(), nullable=True, existing_type=sa.Integer())
        op.alter_column('asset_snapshots', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('execution_orders', 'project_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
        op.alter_column('execution_orders', 'strategy_id', type_=sa.BigInteger(), nullable=False, existing_type=sa.Integer())
    
    else:
        # SQLite approach - skip the migration for now
        # SQLite has severe limitations with ALTER COLUMN
        # For now, we'll just pass and let the application handle the type conversion
        # The models are already updated to use BigInteger, so new records will use the correct type
        pass


def downgrade() -> None:
    """Downgrade schema."""
    # Get the database connection to check the dialect
    connection = op.get_bind()
    is_mysql = connection.dialect.name == 'mysql'
    
    if is_mysql:
        # MySQL downgrade
        try:
            op.drop_constraint('execution_orders_ibfk_1', 'execution_orders', type_='foreignkey')
        except Exception:
            pass
        
        try:
            op.drop_constraint('fk_execution_orders_project_id', 'execution_orders', type_='foreignkey')
        except Exception:
            pass
        
        # Revert all BigInteger fields back to Integer
        op.alter_column('users', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('roles', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('projects', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('project_configs', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('datasources', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('executors', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('strategies', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('positions', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('orders', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('signals', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        op.alter_column('asset_snapshots', 'id', type_=sa.Integer(), nullable=False, autoincrement=True, existing_type=sa.BigInteger())
        
        # Foreign key and reference ID changes
        op.alter_column('projects', 'created_by', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('project_configs', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('datasources', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('executors', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('strategies', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('positions', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('positions', 'strategy_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('orders', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('orders', 'position_id', type_=sa.Integer(), nullable=True, existing_type=sa.BigInteger())
        op.alter_column('orders', 'exec_order_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('orders', 'signal_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('orders', 'strategy_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('orders', 'executor_id', type_=sa.Integer(), nullable=True, existing_type=sa.BigInteger())
        op.alter_column('signals', 'project_id', type_=sa.Integer(), nullable=True, existing_type=sa.BigInteger())
        op.alter_column('signals', 'strategy_id', type_=sa.Integer(), nullable=True, existing_type=sa.BigInteger())
        op.alter_column('asset_snapshots', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('execution_orders', 'project_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
        op.alter_column('execution_orders', 'strategy_id', type_=sa.Integer(), nullable=False, existing_type=sa.BigInteger())
    
    else:
        # SQLite downgrade - skip for now
        pass 