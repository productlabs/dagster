import pandas as pd

from dagster import (
    DependencyDefinition,
    ExecutionContext,
    Field,
    InputDefinition,
    OutputDefinition,
    PipelineDefinition,
    Result,
    SolidDefinition,
    check,
    execute_pipeline,
    lambda_solid,
    types,
)

from dagster.core.test_utils import single_output_transform

from dagster_contrib.pandas import DataFrame


def load_csv_solid(name):
    check.str_param(name, 'name')

    def _t_fn(info, _inputs):
        yield Result(pd.read_csv(info.config['path']))

    return SolidDefinition(
        name=name,
        inputs=[],
        outputs=[OutputDefinition(DataFrame)],
        transform_fn=_t_fn,
        config_field=Field(types.Dict({'path': Field(types.Path)})),
    )


def _dataframe_solid(name, inputs, transform_fn):
    return single_output_transform(
        name=name, inputs=inputs, transform_fn=transform_fn, output=OutputDefinition(DataFrame)
    )


def get_solid_transformed_value(_context, solid_inst):
    pipeline = PipelineDefinition(
        solids=[load_num_csv_solid('load_csv'), solid_inst],
        dependencies={
            solid_inst.name: {solid_inst.input_defs[0].name: DependencyDefinition('load_csv')}
        },
    )

    pipeline_result = execute_pipeline(pipeline)

    execution_result = pipeline_result.result_for_solid(solid_inst.name)

    return execution_result.transformed_value()


def get_num_csv_environment(solids_config):
    return {'solids': solids_config}


def create_test_context():
    return ExecutionContext()


def create_sum_table():
    def transform(_context, inputs):
        num_csv = inputs['num_csv']
        check.inst_param(num_csv, 'num_csv', pd.DataFrame)
        num_csv['sum'] = num_csv['num1'] + num_csv['num2']
        return num_csv

    return _dataframe_solid(
        name='sum_table', inputs=[InputDefinition('num_csv', DataFrame)], transform_fn=transform
    )


@lambda_solid(inputs=[InputDefinition('num_csv', DataFrame)], output=OutputDefinition(DataFrame))
def sum_table(num_csv):
    check.inst_param(num_csv, 'num_csv', pd.DataFrame)
    num_csv['sum'] = num_csv['num1'] + num_csv['num2']
    return num_csv


@lambda_solid(inputs=[InputDefinition('sum_df', DataFrame)], output=OutputDefinition(DataFrame))
def sum_sq_table(sum_df):
    sum_df['sum_squared'] = sum_df['sum'] * sum_df['sum']
    return sum_df


@lambda_solid(
    inputs=[InputDefinition('sum_table_renamed', DataFrame)], output=OutputDefinition(DataFrame)
)
def sum_sq_table_renamed_input(sum_table_renamed):
    sum_table_renamed['sum_squared'] = sum_table_renamed['sum'] * sum_table_renamed['sum']
    return sum_table_renamed


def test_pandas_csv_in_memory():
    df = get_solid_transformed_value(None, create_sum_table())
    assert isinstance(df, pd.DataFrame)
    assert df.to_dict('list') == {'num1': [1, 3], 'num2': [2, 4], 'sum': [3, 7]}


def _sum_only_pipeline():
    return PipelineDefinition(solids=[sum_table, sum_sq_table], dependencies={})


def test_two_input_solid():
    def transform(_context, inputs):
        num_csv1 = inputs['num_csv1']
        num_csv2 = inputs['num_csv2']
        check.inst_param(num_csv1, 'num_csv1', pd.DataFrame)
        check.inst_param(num_csv2, 'num_csv2', pd.DataFrame)
        num_csv1['sum'] = num_csv1['num1'] + num_csv2['num2']
        return num_csv1

    two_input_solid = _dataframe_solid(
        name='two_input_solid',
        inputs=[InputDefinition('num_csv1', DataFrame), InputDefinition('num_csv2', DataFrame)],
        transform_fn=transform,
    )

    pipeline = PipelineDefinition(
        solids=[load_num_csv_solid('load_csv1'), load_num_csv_solid('load_csv2'), two_input_solid],
        dependencies={
            'two_input_solid': {
                'num_csv1': DependencyDefinition('load_csv1'),
                'num_csv2': DependencyDefinition('load_csv2'),
            }
        },
    )

    pipeline_result = execute_pipeline(pipeline)
    assert pipeline_result.success

    df = pipeline_result.result_for_solid('two_input_solid').transformed_value()

    assert isinstance(df, pd.DataFrame)
    assert df.to_dict('list') == {'num1': [1, 3], 'num2': [2, 4], 'sum': [3, 7]}


def test_no_transform_solid():
    num_table = _dataframe_solid(
        name='num_table',
        inputs=[InputDefinition('num_csv', DataFrame)],
        transform_fn=lambda _context, inputs: inputs['num_csv'],
    )
    context = create_test_context()
    df = get_solid_transformed_value(context, num_table)
    assert df.to_dict('list') == {'num1': [1, 3], 'num2': [2, 4]}


def create_diamond_pipeline(extra_solids=None, extra_dependencies=None):
    all_solids = list(create_diamond_dag()) + (extra_solids if extra_solids else [])
    all_deps = {}
    all_deps.update(create_diamond_deps())
    if extra_dependencies:
        all_deps.update(extra_dependencies)
    return PipelineDefinition(solids=all_solids, dependencies=all_deps)


def create_diamond_deps():
    return {
        'num_table': {'num_csv': DependencyDefinition('load_csv')},
        'sum_table': {'num_table': DependencyDefinition('num_table')},
        'mult_table': {'num_table': DependencyDefinition('num_table')},
        'sum_mult_table': {
            'sum_table': DependencyDefinition('sum_table'),
            'mult_table': DependencyDefinition('mult_table'),
        },
    }


def create_diamond_dag():
    load_csv_solid_ = load_csv_solid('load_csv')

    num_table_solid = _dataframe_solid(
        name='num_table',
        inputs=[InputDefinition('num_csv', DataFrame)],
        transform_fn=lambda _context, inputs: inputs['num_csv'],
    )

    def sum_transform(_context, inputs):
        num_df = inputs['num_table']
        sum_df = num_df.copy()
        sum_df['sum'] = num_df['num1'] + num_df['num2']
        return sum_df

    sum_table_solid = _dataframe_solid(
        name='sum_table',
        inputs=[InputDefinition('num_table', DataFrame)],
        transform_fn=sum_transform,
    )

    def mult_transform(_context, inputs):
        num_table = inputs['num_table']
        mult_table = num_table.copy()
        mult_table['mult'] = num_table['num1'] * num_table['num2']
        return mult_table

    mult_table_solid = _dataframe_solid(
        name='mult_table',
        inputs=[InputDefinition('num_table', DataFrame)],
        transform_fn=mult_transform,
    )

    def sum_mult_transform(_context, inputs):
        sum_df = inputs['sum_table']
        mult_df = inputs['mult_table']
        sum_mult_table = sum_df.copy()
        sum_mult_table['mult'] = mult_df['mult']
        sum_mult_table['sum_mult'] = sum_df['sum'] * mult_df['mult']
        return sum_mult_table

    sum_mult_table_solid = _dataframe_solid(
        name='sum_mult_table',
        inputs=[InputDefinition('sum_table', DataFrame), InputDefinition('mult_table', DataFrame)],
        transform_fn=sum_mult_transform,
    )

    return (
        load_csv_solid_,
        num_table_solid,
        sum_table_solid,
        mult_table_solid,
        sum_mult_table_solid,
    )


def _result_for_solid(results, name):
    for result in results:
        if result.name == name:
            return result

    check.failed('could not find name')


def load_num_csv_solid(name):
    @lambda_solid(name=name)
    def _return_num_csv():
        return pd.DataFrame({'num1': [1, 3], 'num2': [2, 4]})

    return _return_num_csv


def test_pandas_multiple_inputs():
    def transform_fn(_context, inputs):
        return inputs['num_csv1'] + inputs['num_csv2']

    double_sum = _dataframe_solid(
        name='double_sum',
        inputs=[InputDefinition('num_csv1', DataFrame), InputDefinition('num_csv2', DataFrame)],
        transform_fn=transform_fn,
    )

    pipeline = PipelineDefinition(
        solids=[load_num_csv_solid('load_one'), load_num_csv_solid('load_two'), double_sum],
        dependencies={
            'double_sum': {
                'num_csv1': DependencyDefinition('load_one'),
                'num_csv2': DependencyDefinition('load_two'),
            }
        },
    )

    output_df = execute_pipeline(pipeline).result_for_solid('double_sum').transformed_value()

    assert not output_df.empty

    assert output_df.to_dict('list') == {'num1': [2, 6], 'num2': [4, 8]}


def test_rename_input():
    result = execute_pipeline(
        PipelineDefinition(
            solids=[load_num_csv_solid('load_csv'), sum_table, sum_sq_table_renamed_input],
            dependencies={
                'sum_table': {'num_csv': DependencyDefinition('load_csv')},
                sum_sq_table_renamed_input.name: {
                    'sum_table_renamed': DependencyDefinition(sum_table.name)
                },
            },
        )
    )

    assert result.success

    expected = {'num1': [1, 3], 'num2': [2, 4], 'sum': [3, 7], 'sum_squared': [9, 49]}
    solid_result = result.result_for_solid('sum_sq_table_renamed_input')
    assert solid_result.transformed_value().to_dict('list') == expected
