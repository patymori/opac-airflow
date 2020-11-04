import os
import logging
import json
from tempfile import mkdtemp
from packtools import SPPackage
from zipfile import ZipFile
from copy import deepcopy
from typing import Dict, List, Tuple, Any

from deepdiff import DeepDiff

from operations.exceptions import (
    DeleteDocFromKernelException,
    DocumentToDeleteException,
    PutXMLInObjectStoreException,
    RegisterUpdateDocIntoKernelException,
    LinkDocumentToDocumentsBundleException,
    Pidv3Exception,
)

from operations.docs_utils import (
    delete_doc_from_kernel,
    is_document_to_delete,
    register_update_doc_into_kernel,
    put_assets_and_pdfs_in_object_store,
    put_xml_into_object_store,
    get_bundle_id,
    update_documents_in_bundle,
    update_aop_bundle_items,
    get_or_create_bundle,
    get_xml_data,
    put_object_in_object_store,
)

Logger = logging.getLogger(__name__)


def list_documents(sps_package):
    """
    Lista todos os XMLs dos SPS Packages da lista obtida do diretório do XC.

    list sps_packages: lista com os paths dos pacotes SPS no diretório de processamento
    dict sps_packages_xmls: dict com os paths dos pacotes SPS e os respectivos nomes dos
        arquivos XML.
    """
    Logger.debug("list_documents IN")
    Logger.info("Reading sps_package: %s" % sps_package)
    with ZipFile(sps_package) as zf:
        xmls_filenames = [
            xml_filename
            for xml_filename in zf.namelist()
            if os.path.splitext(xml_filename)[-1] == ".xml"
        ]
        Logger.debug("list_documents OUT")
        return xmls_filenames


def delete_documents(
    sps_package: str, xmls_filenames: list
) -> Tuple[List[str], List[dict]]:
    """
    Deleta documentos informados do Kernel

    dict sps_packages_xmls: dict com os paths dos pacotes SPS e os respectivos nomes dos
        arquivos XML.
    """
    Logger.debug("delete_documents IN")
    Logger.info("Reading sps_package: %s" % sps_package)
    xmls_to_delete = []
    executions = []

    with ZipFile(sps_package) as zipfile:
        for i, sps_xml_file in enumerate(xmls_filenames, 1):
            Logger.info(
                'Reading XML file "%s" from ZIP file "%s" [%s/%s]',
                sps_xml_file,
                sps_package,
                i,
                len(xmls_filenames),
            )
            execution = {"file_name": sps_xml_file, "deletion": True}
            try:
                is_doc_to_delete, doc_id = is_document_to_delete(zipfile, sps_xml_file)
            except DocumentToDeleteException as exc:
                Logger.error('Error reading document "%s": %s', sps_xml_file, str(exc))
                execution.update({"failed": True, "error": str(exc)})
                executions.append(execution)
            else:
                if is_doc_to_delete:
                    xmls_to_delete.append(sps_xml_file)
                    if doc_id is None:
                        Logger.error(
                            'Document "%s" will not be deleted because SciELO PID is None',
                            sps_xml_file,
                        )
                        execution.update(
                            {"failed": True, "error": "SciELO PID V3 is None"}
                        )
                        executions.append(execution)
                        continue
                    try:
                        delete_doc_from_kernel(doc_id)
                    except DeleteDocFromKernelException as exc:
                        Logger.info(
                            'Could not delete "%s" (scielo_id: "%s") from kernel: %s',
                            sps_xml_file,
                            doc_id,
                            str(exc),
                        )
                        execution.update(
                            {"pid": doc_id, "failed": True, "error": str(exc)}
                        )
                    else:
                        Logger.info(
                            'Document "%s" (scielo_id: "%s") deleted from kernel',
                            sps_xml_file,
                            doc_id,
                        )
                        execution.update({"pid": doc_id, "file_name": sps_xml_file})
                    executions.append(execution)

    Logger.debug("delete_documents OUT")
    return (list(set(xmls_filenames) - set(xmls_to_delete)), executions)


def optimize_sps_pkg_zip_file(sps_pkg_zip_file, new_sps_zip_dir):
    """
    Recebe um zip `sps_pkg_zip_file` e
    Retorna seu zip otimizado `new_sps_pkg_zip_file`
    """
    basename = os.path.basename(sps_pkg_zip_file)
    new_sps_pkg_zip_file = os.path.join(new_sps_zip_dir, basename)

    # Apaga arquivo se já existe antes de otimizar
    if os.path.isfile(new_sps_pkg_zip_file):
        os.unlink(new_sps_pkg_zip_file)

    with ZipFile(sps_pkg_zip_file) as zip_file:
        package = SPPackage(zip_file, new_sps_zip_dir)
        package.optimise(new_package_file_path=new_sps_pkg_zip_file, preserve_files=False)

    if os.path.isfile(new_sps_pkg_zip_file):
        Logger.debug("optimize_sps_pkg_zip_file OUT")
        return new_sps_pkg_zip_file


def register_update_documents(sps_package, xmls_to_preserve):
    """
    Registra/atualiza documentos informados e seus respectivos ativos digitais e
    renditions no Minio e no Kernel.
     list docs_to_preserve: lista de XMLs para manter no Kernel (Registrar ou atualizar)
     Não deve cadastrar documentos que não tenha ``scielo-id``
    """

    executions = []

    Logger.debug("register_update_documents IN")
    with ZipFile(sps_package) as zipfile:

        synchronized_docs_metadata = []
        for i, xml_filename in enumerate(xmls_to_preserve):
            Logger.info(
                'Reading XML file "%s" from ZIP file "%s" [%s/%s]',
                xml_filename,
                sps_package,
                i,
                len(xmls_to_preserve),
            )

            execution = {"file_name": xml_filename}

            try:
                xml_data = put_xml_into_object_store(zipfile, xml_filename)
            except (PutXMLInObjectStoreException, Pidv3Exception) as exc:
                Logger.error(
                    'Could not put document "%s" in object store: %s',
                    xml_filename,
                    str(exc),
                )
                execution.update({"failed": True, "error": str(exc)})
            else:
                assets_and_pdfs_data = put_assets_and_pdfs_in_object_store(zipfile, xml_data)
                _document_metadata = deepcopy(xml_data)
                _document_metadata.update(assets_and_pdfs_data)
                try:
                    register_update_doc_into_kernel(_document_metadata)

                except RegisterUpdateDocIntoKernelException as exc:
                    Logger.error(
                        'Could not register or update document "%s" in Kernel: %s',
                        xml_filename,
                        str(exc),
                    )
                    execution.update(
                        {
                            "pid": xml_data.get("scielo_id"),
                            "failed": True,
                            "error": str(exc),
                        }
                    )
                else:
                    synchronized_docs_metadata.append(xml_data)
                    execution.update(
                        {
                            "pid": xml_data.get("scielo_id"),
                            "payload": _document_metadata,
                        }
                    )
            executions.append(execution)

    Logger.debug("register_update_documents OUT")

    return (synchronized_docs_metadata, executions)


def link_documents_to_documentsbundle(sps_package, documents, issn_index_json_path):
    """
        Relaciona documentos com seu fascículos(DocumentsBundle).

        :param kwargs['sps_package']: Path do pacote SPS com os documentos
        :param kwargs['documents']: Uma lista de dicionários contento os atributos necessários para a descoberta do fascículo.

            Exemplo contendo a lista de atributos(mínimo):
            [
                {
                 "scielo_id": "S0034-8910.2014048004923",
                 "issn": "0034-8910",
                 "year": "2014",
                 "volume": "48",
                 "number": "2",
                 "order": "347",
                 },
                {
                 "scielo_id": "S0034-8910.2014048004924",
                 "issn": "0034-8910",
                 "year": "2014",
                 "volume": "48",
                 "number": "2",
                 "order": "348",
                 },
                {
                 "scielo_id": "S0034-8910.20140078954641",
                 "issn": "1518-8787",
                 "year": "2014",
                 "volume": "02",
                 "number": "2",
                 "order": "978",
                 },
                {
                 "scielo_id": "S0034-8910.20140078954641",
                 "issn": "1518-8787",
                 "year": "2014",
                 "volume": "02",
                 "number": "2",
                 "order": "978",
                 "supplement": "1",
                 }
            ]
        {"id": "0034-8910-2014-v48-n2", "status":204}
        Return a list of document linkd or not, something like:
            [
             {'id': 'S0034-8910.2014048004923', 'status': 204},
             {'id': 'S0034-8910.20140078954641', 'status': 422},
             {'id': 'S0034-8910.20140078923452', 'status': 404},
            ]
    """

    Logger.info("link_documents_to_documentsbundle PUT")

    ret = []
    issn_id = ''
    bundle_id = ''
    bundle_id_doc = {}
    executions = []

    if documents:
        Logger.info('Reading ISSN index file %s', issn_index_json_path)
        with open(issn_index_json_path) as issn_index_file:
            issn_index_json = issn_index_file.read()
            issn_index = json.loads(issn_index_json)
        for doc in documents:
            try:
                issn_id = issn_index[doc["issn"]]
            except KeyError as exc:
                Logger.info(
                    'Could not get journal ISSN ID: ISSN id "%s" not found', doc["issn"]
                )
                executions.append(
                    {
                        "pid": doc.get("scielo_id"),
                        "bundle_id": None,
                        "error": 'Could not get journal ISSN ID: ISSN id "%s" not found'
                        % doc["issn"],
                    }
                )
            else:
                bundle_id = get_bundle_id(issn_id=issn_id,
                                     year=doc.get("year"),
                                     volume=doc.get("volume", None),
                                     number=doc.get("number", None),
                                     supplement=doc.get("supplement", None))

                bundle_id_doc.setdefault(bundle_id, [])

                payload_doc = {}
                payload_doc['id'] = doc.get("scielo_id")
                payload_doc['order'] = doc.get("order")

                bundle_id_doc[bundle_id].append(payload_doc)

        def _update_items_list(new_items: list, current_items: list) -> list:
            """Retorna uma lista links atualizada a partir dos items atuais
            e dos novos items."""

            items = deepcopy(current_items)

            for new_item in new_items:
                for index, current_item in enumerate(items):
                    if new_item["id"] == current_item["id"]:
                        items[index] = new_item
                        break
                else:
                    items.append(new_item)

            return items

        is_aop_bundle = "ahead" in sps_package
        for bundle_id, new_items in bundle_id_doc.items():
            try:
                conn_response = get_or_create_bundle(bundle_id, is_aop=is_aop_bundle)
            except LinkDocumentToDocumentsBundleException as exc:
                ret.append({"id": bundle_id, "status": exc.response.status_code})
                Logger.info("Could not get bundle %: Bundle not found", bundle_id)
                for new_item_relationship in new_items:
                    executions.append(
                        {
                            "pid": new_item_relationship.get("id"),
                            "bundle_id": bundle_id,
                            "failed": True,
                            "error": str(exc)
                        }
                    )
            else:
                current_items = conn_response.json()["items"]
                payload = _update_items_list(new_items, current_items)
                Logger.info("Registering bundle_id %s with %s", bundle_id, payload)

                if DeepDiff(current_items, payload, ignore_order=True):
                    response = update_documents_in_bundle(bundle_id, payload)
                    ret.append({"id": bundle_id, "status": response.status_code})
                    logging.info(
                        "The bundle %s items list has been updated." % bundle_id
                    )

                    for new_item_relationship in new_items:
                        executions.append(
                            {
                                "pid": new_item_relationship.get("id"),
                                "bundle_id": bundle_id,
                            }
                        )
                else:
                    logging.info(
                        "The bundle %s items does not need to be updated." % bundle_id
                    )
                if not is_aop_bundle:
                    try:
                        articles_removed_from_aop = update_aop_bundle_items(
                            issn_id, payload
                        )
                    except LinkDocumentToDocumentsBundleException as exc:
                        Logger.error(str(exc))
                    else:
                        executions.extend(articles_removed_from_aop)

        return (ret, executions)

    Logger.info("link_documents_to_documentsbundle OUT")


def get_document_data(zip_file: ZipFile, xml_filename: str) -> Dict[str, Any]:
    """
    Lê arquivo XML informado de ``zip_file`` e obtém os metadados para sincronização.

    :param zip_file: Instância ZipFile de SPS Package
    :param xml_filename: Nome de arquivo XML no ``zip_file``

    :return: Dict com os dados extraídos do arquivo XML. Em caso de erros, também são
        atribuídos como tal no dicionário.
    """
    document_data = {"file_name": xml_filename}
    try:
        is_doc_to_delete, doc_id = is_document_to_delete(zip_file, xml_filename)
    except DocumentToDeleteException as exc:
        Logger.error('Error reading document "%s": %s', xml_filename, exc)
        document_data.update({"failed": True, "error": str(exc)})
    else:
        document_data["deletion"] = is_doc_to_delete
        xml_data = get_xml_data(
            zip_file.read(xml_filename), os.path.splitext(xml_filename)[-2]
        )
        if xml_data.get("scielo_id"):
            document_data.update(
                {"pid": xml_data.get("scielo_id"), "payload": xml_data}
            )
        else:
            error = f'Could not get scielo id v3 in document "{xml_filename}"'
            Logger.error(error)
            document_data.update({"failed": True, "error": error})

    return document_data


def extract_package_data(sps_package: str) -> Dict[str, dict]:
    """
    Lê todos os documentos XML do ``sps_package`` informado e extrai as informações 
    contidas em cada um deles.

    :param zip_file: Instância ZipFile de SPS Package

    :return: Dict com os dados extraídos por arquivo XML presente no pacote SPS.
    :return: List com os campos de identificação para cada versão do documento
    Ex.:
    {
        "pidv3-0001.xml": {
            "file_name": "pidv3-0001.xml",
            "package_path": "acron-v1n1-1",
            "bundle_id": "0001-0002-2020-v1-n1",
            "deletion": "true",
        },
        "pidv3-0002.xml": {
            "file_name": "pidv3-0002.xml",
            "package_path": "acron-v1n1-2",
            "bundle_id": "0001-0002-2020-v1-n1",
            "deletion": "false",
            "payload": {"field": "data"}
        },
        "pidv3-0002.xml": {
            "file_name": "pidv3-000n.xml",
            "package_path": "acron-v1n1-3",
            "bundle_id": "0001-0002-2020-v1-n1",
            "deletion": "false",
            "payload": {"field": "data"}
        },
    }
    """
    documents_info = {}
    with ZipFile(sps_package) as zip_file:
        xmls_filenames = [
            xml_filename
            for xml_filename in zip_file.namelist()
            if os.path.splitext(xml_filename)[-1] == ".xml"
        ]
        for i, xml_filename in enumerate(xmls_filenames, 1):
            Logger.info(
                'Reading document "%s" from "%s" [%d/%d]',
                xml_filename, sps_package, i, len(xmls_filenames)
            )
            document_data = get_document_data(zip_file, xml_filename)
            document_data.update({"package_path": sps_package})
            documents_info[xml_filename] = document_data
    return documents_info, ["file_name", "package_path"]


def put_document_in_kernel(data: dict) -> dict:
    """
    Registra/atualiza documento no Object Store e no Kernel a partir do conteúdo de 
    ``data``.

    :param data: Dados extraídos a partir do XML no pacote SPS.

    :return: Dict com o resultado da execução. Se houver falha, conterá o erro. Caso 
    contrário, o payload com os dados para o relacionamento do documento com o bundle
    """
    xml_data = deepcopy(data["payload"])
    Logger.info('Putting XML file "%s" to Object Store', data["file_name"])
    with ZipFile(data["package_path"]) as zip_file:
        xml_data["xml_url"] = put_object_in_object_store(
            zip_file.read(data["file_name"]),
            xml_data["issn"],
            xml_data["scielo_id"],
            data["file_name"],
        )
        assets_and_pdfs_data = put_assets_and_pdfs_in_object_store(
            zip_file, xml_data
        )

    xml_data.update(assets_and_pdfs_data)
    register_update_doc_into_kernel(xml_data)
    execution = {"failed": False, "payload": xml_data}
    return xml_data, execution
