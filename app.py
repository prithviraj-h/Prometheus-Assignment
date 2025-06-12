from flask import Flask, render_template, request, redirect, url_for, flash
import boto3
import os
from dotenv import load_dotenv
from prometheus_client import make_wsgi_app, Counter, Histogram, Gauge
from werkzeug.middleware.dispatcher import DispatcherMiddleware
import psutil
import time

load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for flashing messages

REQUEST_COUNT = Counter(
    'flask_request_count',
    'Application Request Count',
    ['method', 'endpoint', 'http_status']
)

REQUEST_LATENCY = Histogram(
    'flask_request_latency_seconds',
    'Application Request Latency',
    ['method', 'endpoint']
)

MEMORY_USAGE = Gauge(
    'flask_memory_usage_bytes',
    'Application Memory Usage'
)

CPU_USAGE = Gauge(
    'flask_cpu_usage_percent',
    'Application CPU Usage'
)

app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
    '/metrics': make_wsgi_app()
})

@app.before_request
def before_request():
    request.start_time = time.time()

@app.after_request
def after_request(response):
    # Record metrics
    request_latency = time.time() - request.start_time
    REQUEST_LATENCY.labels(request.method, request.path).observe(request_latency)
    REQUEST_COUNT.labels(request.method, request.path, response.status_code).inc()
    MEMORY_USAGE.set(psutil.Process(os.getpid()).memory_info().rss)
    CPU_USAGE.set(psutil.cpu_percent())
    return response

# AWS S3 Configuration
s3 = boto3.client('s3')

@app.route('/')
def index():
    buckets = s3.list_buckets().get('Buckets', [])
    return render_template('index.html', buckets=buckets)

#@app.route('/bucket/<bucket_name>')
#def list_bucket(bucket_name):
 #   objects = s3.list_objects_v2(Bucket=bucket_name).get('Contents', [])
  #  return render_template('list_bucket.html', bucket_name=bucket_name, objects=objects)

@app.route('/bucket/<bucket_name>')
def list_bucket(bucket_name):
    prefix = request.args.get('prefix', '')  # Optional folder path
    paginator = s3.get_paginator('list_objects_v2')
    result = paginator.paginate(Bucket=bucket_name, Prefix=prefix, Delimiter='/')

    folders = []
    files = []

    for page in result:
        folders += page.get('CommonPrefixes', [])
        files += page.get('Contents', [])

    return render_template('list_bucket.html', bucket_name=bucket_name, objects=files, folders=folders, current_prefix=prefix)


@app.route('/create_bucket', methods=['POST'])
def create_bucket():
    bucket_name = request.form['bucket_name']
    try:
        s3.create_bucket(Bucket=bucket_name)
        flash(f"Bucket '{bucket_name}' created successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('index'))

@app.route('/delete_bucket/<bucket_name>', methods=['POST'])
def delete_bucket(bucket_name):
    try:
        s3.delete_bucket(Bucket=bucket_name)
        flash(f"Bucket '{bucket_name}' deleted successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('index'))

@app.route('/upload/<bucket_name>', methods=['POST'])
def upload_file(bucket_name):
    file = request.files['file']
    key = request.form.get('key', file.filename)
    
    try:
        s3.upload_fileobj(file, bucket_name, key)
        flash(f"File '{key}' uploaded successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")
    
    # Redirect to the folder where the file was uploaded
    parent_prefix = os.path.dirname(key)
    if parent_prefix and not parent_prefix.endswith('/'):
        parent_prefix += '/'
    return redirect(url_for('list_bucket', bucket_name=bucket_name, prefix=parent_prefix))


@app.route('/delete_file/<bucket_name>/<path:key>', methods=['POST'])
def delete_file(bucket_name, key):
    try:
        s3.delete_object(Bucket=bucket_name, Key=key)
        flash(f"File '{key}' deleted successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('list_bucket', bucket_name=bucket_name))

@app.route('/delete_folder/<bucket_name>', methods=['POST'])
def delete_folder(bucket_name):
    prefix = request.form['prefix']

    try:
        # List and delete all objects with this prefix
        objects_to_delete = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix).get('Contents', [])
        for obj in objects_to_delete:
            s3.delete_object(Bucket=bucket_name, Key=obj['Key'])

        flash(f"Folder '{prefix}' and all its contents deleted successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('list_bucket', bucket_name=bucket_name, prefix=os.path.dirname(prefix) + '/'))


@app.route('/create_folder/<bucket_name>', methods=['POST'])
def create_folder(bucket_name):
    folder_name = request.form['folder_name']
    if not folder_name.endswith('/'):
        folder_name += '/'
    try:
        s3.put_object(Bucket=bucket_name, Key=folder_name)
        flash(f"Folder '{folder_name}' created successfully.", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('list_bucket', bucket_name=bucket_name))

@app.route('/copy_move/<bucket_name>', methods=['POST'])
def copy_move_file(bucket_name):
    source_key = request.form['source_key']
    destination_key = request.form['destination_key']
    operation = request.form['operation']  # copy or move

    try:
        copy_source = {'Bucket': bucket_name, 'Key': source_key}
        s3.copy_object(CopySource=copy_source, Bucket=bucket_name, Key=destination_key)
        if operation == 'move':
            s3.delete_object(Bucket=bucket_name, Key=source_key)
        flash(f"File '{operation}' operation successful.", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for('list_bucket', bucket_name=bucket_name))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001) #app.run(debug=True, port=int(os.getenv('FLASK_RUN_PORT', 5001)))