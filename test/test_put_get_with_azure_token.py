#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2019 Snowflake Computing Inc. All right reserved.
#

import glob
import gzip
import os
import sys
import time
from logging import getLogger

import pytest

from snowflake.connector.constants import UTF8

try:
    from parameters import (CONNECTION_PARAMETERS_ADMIN)
except:
    CONNECTION_PARAMETERS_ADMIN = {}

logger = getLogger(__name__)

# Mark every test in this module as an azure and a putget test
pytestmark = [pytest.mark.azure, pytest.mark.putget]


@pytest.mark.skipif(
    not CONNECTION_PARAMETERS_ADMIN,
    reason="Snowflake admin account is not accessible."
)
def test_put_get_with_azure(tmpdir, conn_cnx, db_parameters):
    """
    [azure] Put and Get a small text using Azure
    """
    # create a data file
    fname = str(tmpdir.join('test_put_get_with_azure_token.txt.gz'))
    with gzip.open(fname, 'wb') as f:
        original_contents = "123,test1\n456,test2\n"
        f.write(original_contents.encode(UTF8))
    tmp_dir = str(tmpdir.mkdir('test_put_get_with_azure_token'))

    with conn_cnx(
            user=db_parameters['azure_user'],
            account=db_parameters['azure_account'],
            password=db_parameters['azure_password']) as cnx:
        with cnx.cursor() as csr:
            csr.execute("rm @~/snow32806")
            csr.execute(
                "create or replace table snow32806 (a int, b string)")
            try:

                csr.execute(
                    "put file://{0} @%snow32806 auto_compress=true parallel=30".format(
                        fname))
                rec = csr.fetchone()
                assert rec[6] == u'UPLOADED'
                csr.execute("copy into snow32806")
                csr.execute(
                    "copy into @~/snow32806 from snow32806 "
                    "file_format=( format_name='common.public.csv' "
                    "compression='gzip')")
                csr.execute(
                    "get @~/snow32806 file://{0} pattern='snow32806.*'".format(
                        tmp_dir))
                rec = csr.fetchone()
                assert rec[0].startswith(
                    'snow32806'), 'A file downloaded by GET'
                assert rec[1] == 36, 'Return right file size'
                assert rec[2] == u'DOWNLOADED', 'Return DOWNLOADED status'
                assert rec[3] == u'', 'Return no error message'
            finally:
                csr.execute("drop table snow32806")
                csr.execute("rm @~/snow32806")

    files = glob.glob(os.path.join(tmp_dir, 'snow32806*'))
    with gzip.open(files[0], 'rb') as fd:
        contents = fd.read().decode(UTF8)
    assert original_contents == contents, (
        'Output is different from the original file')


@pytest.mark.skipif(
    not CONNECTION_PARAMETERS_ADMIN or os.getenv("SNOWFLAKE_GCP") is not None,
    reason="Snowflake admin account is not accessible."
)
def test_put_copy_many_files_azure(tmpdir, test_files, conn_cnx, db_parameters):
    """
    [azure] Put and Copy many files
    """
    # generates N files
    number_of_files = 10
    number_of_lines = 1000
    tmp_dir = test_files(tmpdir, number_of_lines, number_of_files)

    files = os.path.join(tmp_dir, 'file*')

    def run(csr, sql):
        sql = sql.format(
            files=files,
            name=db_parameters['name'])
        return csr.execute(sql).fetchall()

    with conn_cnx(
            user=db_parameters['azure_user'],
            account=db_parameters['azure_account'],
            password=db_parameters['azure_password']) as cnx:
        with cnx.cursor() as csr:
            run(csr, """
            create or replace table {name} (
            aa int,
            dt date,
            ts timestamp,
            tsltz timestamp_ltz,
            tsntz timestamp_ntz,
            tstz timestamp_tz,
            pct float,
            ratio number(6,2))
            """)
            try:
                all_recs = run(csr, "put file://{files} @%{name}")
                assert all([rec[6] == u'UPLOADED' for rec in all_recs])
                run(csr, "copy into {name}")

                rows = sum([rec[0] for rec in run(csr, "select count(*) from "
                                                       "{name}")])
                assert rows == number_of_files * number_of_lines, \
                    'Number of rows'
            finally:
                run(csr, "drop table if exists {name}")


@pytest.mark.skipif(
    not CONNECTION_PARAMETERS_ADMIN or os.getenv("SNOWFLAKE_GCP") is not None,
    reason="Snowflake admin account is not accessible."
)
def test_put_copy_duplicated_files_azure(tmpdir, test_files, conn_cnx,
                                         db_parameters):
    """
    [azure] Put and Copy duplicated files
    """
    # generates N files
    number_of_files = 5
    number_of_lines = 100
    tmp_dir = test_files(tmpdir, number_of_lines, number_of_files)

    files = os.path.join(tmp_dir, 'file*')

    def run(csr, sql):
        sql = sql.format(
            files=files,
            name=db_parameters['name'])
        return csr.execute(sql, _raise_put_get_error=False).fetchall()

    with conn_cnx(
            user=db_parameters['azure_user'],
            account=db_parameters['azure_account'],
            password=db_parameters['azure_password']) as cnx:
        with cnx.cursor() as csr:
            run(csr, """
            create or replace table {name} (
            aa int,
            dt date,
            ts timestamp,
            tsltz timestamp_ltz,
            tsntz timestamp_ntz,
            tstz timestamp_tz,
            pct float,
            ratio number(6,2))
            """)

            try:
                success_cnt = 0
                skipped_cnt = 0
                for rec in run(csr, "put file://{files} @%{name}"):
                    logger.info('rec=%s', rec)
                    if rec[6] == 'UPLOADED':
                        success_cnt += 1
                    elif rec[6] == 'SKIPPED':
                        skipped_cnt += 1
                assert success_cnt == number_of_files, 'uploaded files'
                assert skipped_cnt == 0, 'skipped files'

                deleted_cnt = 0
                run(csr, "rm @%{name}/file0")
                deleted_cnt += 1
                run(csr, "rm @%{name}/file1")
                deleted_cnt += 1
                run(csr, "rm @%{name}/file2")
                deleted_cnt += 1

                success_cnt = 0
                skipped_cnt = 0
                for rec in run(csr, "put file://{files} @%{name}"):
                    logger.info('rec=%s', rec)
                    if rec[6] == 'UPLOADED':
                        success_cnt += 1
                    elif rec[6] == 'SKIPPED':
                        skipped_cnt += 1
                assert success_cnt == deleted_cnt, \
                    'uploaded files in the second time'
                assert skipped_cnt == number_of_files - deleted_cnt, \
                    'skipped files in the second time'

                run(csr, "copy into {name}")
                rows = 0
                for rec in run(csr, "select count(*) from {name}"):
                    rows += rec[0]
                assert rows == number_of_files * number_of_lines, \
                    'Number of rows'
            finally:
                run(csr, "drop table if exists {name}")


@pytest.mark.skipif(
    not CONNECTION_PARAMETERS_ADMIN,
    reason="Snowflake admin account is not accessible."
)
def test_put_get_large_files_azure(tmpdir, test_files, conn_cnx, db_parameters):
    """
    [azure] Put and Get Large files
    """
    number_of_files = 3
    number_of_lines = 200000
    tmp_dir = test_files(tmpdir, number_of_lines, number_of_files)

    files = os.path.join(tmp_dir, 'file*')
    output_dir = os.path.join(tmp_dir, 'output_dir')
    os.makedirs(output_dir)

    class cb(object):
        def __init__(self, filename, filesize, **_):
            pass

        def __call__(self, bytes_amount):
            pass

    def run(cnx, sql):
        return cnx.cursor().execute(
            sql.format(
                files=files,
                dir=db_parameters['name'],
                output_dir=output_dir),
            _put_callback_output_stream=sys.stdout,
            _get_callback_output_stream=sys.stdout,
            _get_callback=cb,
            _put_callback=cb).fetchall()

    with conn_cnx(
            user=db_parameters['azure_user'],
            account=db_parameters['azure_account'],
            password=db_parameters['azure_password']) as cnx:
        try:
            all_recs = run(cnx, "PUT file://{files} @~/{dir}")
            assert all([rec[6] == u'UPLOADED' for rec in all_recs])

            for _ in range(60):
                for _ in range(100):
                    all_recs = run(cnx, "LIST @~/{dir}")
                    if len(all_recs) == number_of_files:
                        break
                    # you may not get the files right after PUT command
                    # due to the nature of Azure blob, which synchronizes
                    # data eventually.
                    time.sleep(1)
                else:
                    # wait for another second and retry.
                    # this could happen if the files are partially available
                    # but not all.
                    time.sleep(1)
                    continue
                break  # success
            else:
                pytest.fail(
                    'cannot list all files. Potentially '
                    'PUT command missed uploading Files: {0}'.format(all_recs))
            all_recs = run(cnx, "GET @~/{dir} file://{output_dir}")
            assert len(all_recs) == number_of_files
            assert all([rec[2] == 'DOWNLOADED' for rec in all_recs])
        finally:
            run(cnx, "RM @~/{dir}")
