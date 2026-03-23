import boto3

sm = boto3.client('sagemaker', region_name='ap-northeast-2')

BUCKET = 'pre-project-practice-hyunwoo-666803869796-ap-northeast-2-an'
ROLE = 'arn:aws:iam::666803869796:role/SKKU_SageMaker_Role'
CONTAINER = '763104351884.dkr.ecr.ap-northeast-2.amazonaws.com/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker'

response = sm.create_training_job(
    TrainingJobName='densenet121-full-pa-v3',
    RoleArn=ROLE,
    AlgorithmSpecification={'TrainingImage': CONTAINER, 'TrainingInputMode': 'File'},
    HyperParameters={
        'sagemaker_program': 'train.py',
        'sagemaker_submit_directory': f's3://{BUCKET}/code/densenet_full_sourcedir.tar.gz',
        'sagemaker_region': 'ap-northeast-2',
        'batch-size': '32',
        'stage1-epochs': '5',
        'stage2-epochs': '25',
        'image-bucket': 'say1-pre-project-5',
        'work-bucket': BUCKET,
    },
    InputDataConfig=[{
        'ChannelName': 'csv',
        'DataSource': {'S3DataSource': {
            'S3DataType': 'S3Prefix',
            'S3Uri': f's3://{BUCKET}/mimic-cxr-csv/',
            'S3DataDistributionType': 'FullyReplicated'
        }}
    }],
    ResourceConfig={'InstanceType': 'ml.g5.xlarge', 'InstanceCount': 1, 'VolumeSizeInGB': 150},
    CheckpointConfig={'S3Uri': f's3://{BUCKET}/checkpoints/densenet121-full-pa-v3/'},
    OutputDataConfig={'S3OutputPath': f's3://{BUCKET}/output/'},
    EnableManagedSpotTraining=True,
    StoppingCondition={'MaxRuntimeInSeconds': 21600, 'MaxWaitTimeInSeconds': 172800},
    Tags=[{'Key': 'name', 'Value': 'say2-preproject-6team-hyunwoo'}]
)
print('제출 완료: densenet121-full-pa-v3')
