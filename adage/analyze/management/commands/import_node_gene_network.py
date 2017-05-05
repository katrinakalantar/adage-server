"""
This management command will read an input node-gene network file and
populate the "Participation" table in the database.  A valid input file
must be tab-delimited and each line must start with a valid node name,
followed by systematic names of genes that are related to this node.

Here is an example input file:
  adage-server/data/node_gene_network.txt

The command requires three arguments:
  (1) node_gene_network_file: the name of input node-gene network file;
  (2) ml_model_name: the name of machine learning model of the nodes in
      node_gene_network_file. (This argument is needed because a node's
      name may not be unique in the database, but its name and ml_model
      are unique together.)
  (3) participation_type_name: the name of the type of participation of
      the genes in the nodes. A couple of examples are:
      "High weight genes", and "PatternMarker".


For example, to import the data lines in an input file "node_gene_network.txt"
whose machine leaning model is "Ensemble ADAGE 300", we will type:
  python manage.py import_node_gene_network /path/of/node_gene_network.txt \
"Ensemble ADAGE 300" "High weight genes"

IMPORTANT:
Before running this command, please:
  (1) Make sure that ml_model_name already exists in the database.
      If it doesn't, you can use the management command "add_ml_model.py"
      to add it into the database.
  (2) Make sure that the participation_type_name already exists in the
      database. If it doesn't, you can use the management command
      "create_or_update_participation_type.py" to add it into the database.
"""

from __future__ import print_function
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from genes.models import Gene
from analyze.models import MLModel, Node, Participation, ParticipationType

import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Command(BaseCommand):
    help = ("Imports node-gene network data into Participation table in the "
            "database.")

    def add_arguments(self, parser):
        parser.add_argument('node_gene_network_file', type=file)
        parser.add_argument('ml_model_name', type=str)
        parser.add_argument('participation_type_name', type=str)

    def handle(self, **options):
        try:
            import_network(options['node_gene_network_file'],
                           options['ml_model_name'],
                           options['participation_type_name'])
            self.stdout.write(self.style.NOTICE(
                "Node-gene network data imported successfully"))
        except Exception as e:
            raise CommandError(
                "Failed to import Node-gene network data: %s" % e)


def import_network(file_handle, ml_model_name, participation_type_name):
    """
    This function tries to import node-gene network data in the database.
    It first validates input ml_model_name, then reads each valid data
    line in the input file into the database.  The whole reading/importing
    process is enclosed by a transaction context manager so that any
    exception raised inside the manager due to the error detected in
    file_handle will terminate the transaction and roll back the database.
    More details can be found at:
    https://docs.djangoproject.com/en/dev/topics/db/transactions/#controlling-transactions-explicitly
    """

    # Raise an exception if ml_model_name does not exist in the database.
    try:
        ml_model = MLModel.objects.get(title=ml_model_name)
    except MLModel.DoesNotExist:
        raise Exception("Input machine learning model (%s) does NOT exist "
                        "in the database" % ml_model_name)

    # Raise an exception if participation_type_name does not exist in
    # the database.
    try:
        participation_type = ParticipationType.objects.get(
            name=participation_type_name)
    except ParticipationType.DoesNotExist:
        raise Exception("Input participation type (%s) does NOT exist in the "
                        "database" % participation_type_name)

    # Enclose reading/importing process in a transaction.
    with transaction.atomic():
        check_and_import(file_handle, ml_model, participation_type)


def check_and_import(file_handle, ml_model, participation_type):
    """
    Read valid data lines into the database.  An exception will be raised
    if any errors are detected in file_handle.
    """
    nodes_in_file = set()
    for line_index, line in enumerate(file_handle):
        tokens = line.rstrip("\t\r\n").split("\t")
        # Skip a line if it is blank or has only one field.
        if len(tokens) < 2:
            continue

        node_name = tokens[0]
        gene_names = tokens[1:]
        # Raise exception if the node name is duplicate in the file.
        if node_name in nodes_in_file:
            raise Exception("Input file line #%s: %s is a duplicate node in "
                            "the file" % (line_index + 1, node_name))

        try:
            node = Node.objects.get(name=node_name, mlmodel=ml_model)
        except Node.DoesNotExist:
            raise Exception("Input file line #%s: Node name %s not found in "
                            "database" % (line_index + 1, node_name))

        records = []
        for sys_name in gene_names:
            try:
                gene = Gene.objects.get(systematic_name=sys_name)
            # If the gene's sytematic name does not match one and only
            # one gene in the database, generate a warning message and
            # skip this gene.
            except Gene.DoesNotExist:
                logger.warning("Input file line #%s: Gene name %s is skipped "
                               "because it is not found in the database",
                               line_index + 1, sys_name)
                continue
            except Gene.MultipleObjectsReturned:
                logger.warning("Input file line #%s: Gene name %s is skipped "
                               "because multiple genes are named %s in the "
                               "database", line_index + 1, sys_name)
                continue

            # Raise an exception if the combination of (node, gene,
            # participation_type) already exists in Participation table.
            # Instead of relying on the IntegrityError exception
            # implicitly, we raise an explicit exception that includes the
            # input file's line number where the error is detected, and
            # node name, gene name, and participation_type name involved.
            if Participation.objects.filter(
                    node=node, gene=gene,
                    participation_type=participation_type).exists():
                raise Exception("Input file line #%s: (%s, %s, %s) already "
                                "exists in Participation table." %
                                (line_index + 1, node_name, sys_name,
                                 participation_type.name))
            else:
                records.append(
                    Participation(node=node,
                                  gene=gene,
                                  participation_type=participation_type)
                )

        # Create database records in bulk.
        Participation.objects.bulk_create(records)

        # Save this node name so that we can check node duplicate(s) in
        # the file later.
        nodes_in_file.add(node_name)
