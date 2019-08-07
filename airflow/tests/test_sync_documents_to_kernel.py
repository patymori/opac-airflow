from unittest import TestCase, main
from unittest.mock import patch, MagicMock

from airflow import DAG

from package_process import list_documents, delete_documents


class TestListDocuments(TestCase):
    @patch("package_process.docs_operations.list_documents")
    def test_list_document_gets_sps_package_from_dag_run_conf(self, mk_list_documents):
        mk_dag_run = MagicMock()
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        list_documents(**kwargs)
        mk_dag_run.conf.get.assert_called_once_with("sps_package")

    @patch("package_process.docs_operations.list_documents")
    def test_list_document_calls_list_documents_operation(self, mk_list_documents):
        mk_dag_run = MagicMock()
        mk_dag_run.conf.get.return_value = "path_to_sps_package/package.zip"
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        list_documents(**kwargs)
        mk_list_documents.assert_called_once_with("path_to_sps_package/package.zip")

    @patch("package_process.docs_operations.list_documents")
    def test_list_document_pushes_xmls_from_packages(self, mk_list_documents):
        expected = [
            "1806-907X-rba-53-01-1-8.xml",
            "1806-907X-rba-53-01-9-18.xml",
            "1806-907X-rba-53-01-19-25.xml",
        ]
        mk_dag_run = MagicMock()
        mk_dag_run.conf.get.return_value = "path_to_sps_package/package.zip"
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        mk_list_documents.return_value = expected
        list_documents(**kwargs)
        kwargs["ti"].xcom_push.assert_called_once_with(
            key="xmls_filenames", value=expected
        )

    @patch("package_process.docs_operations.list_documents")
    def test_list_document_doesnt_call_ti_xcom_push_if_no_xml_files(
        self, mk_list_documents
    ):
        mk_dag_run = MagicMock()
        mk_dag_run.conf.get.return_value = "path_to_sps_package/package.zip"
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        mk_list_documents.return_value = []
        list_documents(**kwargs)
        kwargs["ti"].xcom_push.assert_not_called()


class TestDeleteDocuments(TestCase):
    @patch("package_process.docs_operations.delete_documents")
    def test_delete_documents_gets_sps_package_from_dag_run_conf(
        self, mk_delete_documents
    ):
        mk_dag_run = MagicMock()
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        delete_documents(**kwargs)
        mk_dag_run.conf.get.assert_called_once_with("sps_package")

    @patch("package_process.docs_operations.delete_documents")
    def test_delete_documents_gets_ti_xcom_info(self, mk_delete_documents):
        mk_dag_run = MagicMock()
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        delete_documents(**kwargs)
        kwargs["ti"].xcom_pull.assert_called_once_with(
            key="xmls_filenames", task_ids="list_docs_task_id"
        )

    @patch("package_process.docs_operations.delete_documents")
    def test_delete_documents_empty_ti_xcom_info(self, mk_delete_documents):
        mk_dag_run = MagicMock()
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        kwargs["ti"].xcom_pull.return_value = None
        delete_documents(**kwargs)
        mk_delete_documents.assert_not_called()
        kwargs["ti"].xcom_push.assert_not_called()

    @patch("package_process.docs_operations.delete_documents")
    def test_delete_documents_calls_delete_documents_operation(
        self, mk_delete_documents
    ):
        xmls_filenames = [
            "1806-907X-rba-53-01-1-8.xml",
            "1806-907X-rba-53-01-9-18.xml",
            "1806-907X-rba-53-01-19-25.xml",
        ]
        mk_dag_run = MagicMock()
        mk_dag_run.conf.get.return_value = "path_to_sps_package/package.zip"
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        kwargs["ti"].xcom_pull.return_value = xmls_filenames
        delete_documents(**kwargs)
        mk_delete_documents.assert_called_once_with(
            "path_to_sps_package/package.zip", xmls_filenames
        )

    @patch("package_process.docs_operations.delete_documents")
    def test_delete_documents_pushes_xmls_to_preserve(self, mk_delete_documents):
        xmls_filenames = [
            "1806-907X-rba-53-01-1-8.xml",
            "1806-907X-rba-53-01-9-18.xml",
            "1806-907X-rba-53-01-19-25.xml",
        ]
        xmls_to_preserve = [
            "1806-907X-rba-53-01-9-18.xml",
            "1806-907X-rba-53-01-19-25.xml",
        ]
        mk_dag_run = MagicMock()
        mk_dag_run.conf.get.return_value = "path_to_sps_package/package.zip"
        kwargs = {"ti": MagicMock(), "dag_run": mk_dag_run}
        kwargs["ti"].xcom_pull.return_value = xmls_filenames
        mk_delete_documents.return_value = xmls_to_preserve
        delete_documents(**kwargs)
        kwargs["ti"].xcom_push.assert_called_once_with(
            key="xmls_to_preserve", value=xmls_to_preserve
        )


if __name__ == "__main__":
    main()