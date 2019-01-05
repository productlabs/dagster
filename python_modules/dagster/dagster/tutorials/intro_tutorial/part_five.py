from dagster import PipelineDefinition, execute_pipeline, solid


@solid
def debug_message(info):
    info.context.debug('A debug message.')
    return 'foo'


@solid
def error_message(info):
    info.context.error('An error occurred.')
    raise Exception()


def define_execution_context_pipeline_step_one():
    return PipelineDefinition(solids=[debug_message, error_message])


def define_execution_context_pipeline_step_two():
    return PipelineDefinition(name='part_five_pipeline', solids=[debug_message, error_message])


def define_execution_context_pipeline_step_three():
    return PipelineDefinition(name='part_five_pipeline', solids=[debug_message, error_message])


if __name__ == '__main__':
    execute_pipeline(
        define_execution_context_pipeline_step_three(),
        {'context': {'default': {'config': {'log_level': 'DEBUG'}}}},
    )
