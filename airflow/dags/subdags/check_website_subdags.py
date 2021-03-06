import logging

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python_operator import PythonOperator

from operations.check_website_operations import (
    group_documents_by_issue_pid_v2,
)


Logger = logging.getLogger(__name__)


def _group_documents_by_issue_pid_v2(args, default_uri_items=None):
    Logger.debug(args)
    try:
        uri_items = Variable.get(
            "_sci_arttext", default_var=[], deserialize_json=True)
        Logger.debug("Variable: %s", uri_items)
    except Exception:
        # sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) 
        # could not connect to server: Connection refused
        uri_items = args.get("_sci_arttext") or []
        Logger.debug("args: %s", uri_items)
    uri_items = uri_items or default_uri_items or []
    Logger.debug("create_subdag for %i", len(uri_items))
    return group_documents_by_issue_pid_v2(uri_items)


def create_subdag_to_check_documents_deeply_grouped_by_issue_pid_v2(
        dag, subdag_callable, group_documents_callable, args):
    """
    Cria uma subdag para executar check_documents_deeply em lotes menores
    para facilitar a reexecução
    """
    Logger.debug("Create check_documents_deeply subdag")

    groups = group_documents_callable(args)
    Logger.debug("%s", groups)
    parent_dag_name = 'check_website'
    child_dag_name = 'check_documents_deeply_grouped_by_issue_pid_v2_id'

    dag_subdag = DAG(
        dag_id='{}.{}'.format(parent_dag_name, child_dag_name),
        default_args=args,
        schedule_interval=None,
    )
    # FIXME
    dag_run_data = {}
    with dag_subdag:
        Logger.debug("%i", len(groups.items()))
        for k, uri_items in groups.items():
            id = k
            task_id = '{}_{}'.format(child_dag_name, id)

            Logger.debug("%s", k)
            Logger.debug("%s", uri_items)
            Logger.debug("%s", task_id)

            PythonOperator(
                task_id=task_id,
                python_callable=subdag_callable,
                op_args=(uri_items, dag_run_data),
                dag=dag_subdag,
            )
        if not groups:
            Logger.debug("Do nothing")
            task_id = f'{child_dag_name}_do_nothing'
            PythonOperator(
                task_id=task_id,
                python_callable=do_nothing,
                dag=dag_subdag,
            )

    return dag_subdag


def do_nothing(**kwargs):
    return True
