#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2012-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import os.path

from edb.testbase import lang as tb
from edb.tools import test

from edb.edgeql import compiler
from edb.edgeql import parser as qlparser
from edb.pgsql import compiler as pg_compiler


class TestEdgeQLSQLCodegen(tb.BaseEdgeQLCompilerTest):
    """Tests for specfic details of the generated SQL.

    Tests can be written by inspecting the AST or the generated text.
    """

    SCHEMA = os.path.join(os.path.dirname(__file__), 'schemas',
                          'cards.esdl')

    def _compile_to_tree(self, source):
        qltree = qlparser.parse(source)
        ir = compiler.compile_ast_to_ir(
            qltree,
            self.schema,
            options=compiler.CompilerOptions(
                modaliases={None: 'default'},
            ),
        )
        return pg_compiler.compile_ir_to_sql_tree(
            ir,
            output_format=pg_compiler.OutputFormat.NATIVE,
        )

    def _compile(self, source):
        qtree = self._compile_to_tree(source)
        return ''.join(pg_compiler.run_codegen(qtree).result)

    @test.xfail('''
        Issue #2567: We generate a pointless self join
    ''')
    def test_codegen_no_self_join(self):
        sql = self._compile('''
            SELECT User.deck.name
        ''')

        # Make sure that User is only selected from *once* in the query
        user_obj = self.schema.get('default::User')
        user_id_str = str(user_obj.id)

        self.assertEqual(
            sql.count(user_id_str), 1, "User table referenced more than once"
        )
