import time
import flask
from flask_sqlalchemy_session import current_session

from cirrus import GoogleCloudManager
from cirrus.google_cloud import get_valid_service_account_id_for_client
from fence.models import GoogleServiceAccountKey
from fence.models import UserGoogleAccount
from fence.models import GoogleServiceAccount
from fence.errors import InternalError


def get_or_create_users_primary_google_service_account_key(
        user_id, proxy_group_id, expires=None):
    """
    Get or create a key for the user's primary service account in their
    proxy group.

    If a key is not stored in the db this will create a new one with
    the provided expiration (or use the default).

    WARNING: If the service account key already exists, the `expires` param
             given will be ignored.

    Args:
        user_id (str): user identifier
        proxy_group_id (str): user's google proxy group identifier
        expires (int, optional): unix time to expire the newly created SA key
            (only used if a new key is required!)

    Returns:
        dict: JSON Google Credentials

    Raises:
        InternalError: User doesn't have a primary service account
    """
    sa_private_key = {}
    # Note that client_id is None, which is how we store the user's SA
    user_google_service_account = (
        get_google_service_account_for_client(client_id=None, user_id=user_id)
    )

    if not user_google_service_account:
        raise InternalError(
            'User {} does not have a primary service account. '
            'Unable to get primary service account key. This service account '
            'should automatically get created when the user\'s proxy group '
            'was created.'.format(user_id)
        )

    user_service_account_key = (
        current_session.query(GoogleServiceAccountKey)
        .filter(
            GoogleServiceAccountKey.service_account_id ==
            user_google_service_account.id)
        .filter(
            GoogleServiceAccountKey.private_key.isnot(None))
        .first()
    )

    if user_service_account_key:
        sa_private_key = user_service_account_key.private_key
    else:
        sa_private_key = _create_users_primary_google_service_account_key(
            user_id, proxy_group_id, expires)

    return sa_private_key, user_service_account_key


def create_users_primary_google_service_account_key(
        user_id, proxy_group_id, expires=None):
    """
    Create a key for the user's primary service account in their
    proxy group.

    This will create a new key with the provided expiration
    (or use the default).

    Args:
        user_id (str): user identifier
        proxy_group_id (str): user's google proxy group identifier
        expires (int, optional): unix time to expire the newly created SA key

    Returns:
        dict: JSON Google Credentials

    Raises:
        InternalError: User doesn't have a primary service account
    """
    # Note that client_id is None, which is how we store the user's SA
    user_google_service_account = (
        get_google_service_account_for_client(client_id=None, user_id=user_id)
    )

    if not user_google_service_account:
        raise InternalError(
            'User {} does not have a primary service account. '
            'Unable to get primary service account key. This service account '
            'should automatically get created when the user\'s proxy group '
            'was created.'.format(user_id)
        )

    return _create_users_primary_google_service_account_key(
        user_id, proxy_group_id, expires)


def create_google_access_key_for_client(client_id, user_id, proxy_group_id):
    """
    Return an access key for current user and client.

    Returns:

        JSON key in Google Credentials File format:

        .. code-block:: JavaScript

            {
                "type": "service_account",
                "project_id": "project-id",
                "private_key_id": "some_number",
                "private_key": "-----BEGIN PRIVATE KEY-----\n....
                =\n-----END PRIVATE KEY-----\n",
                "client_email": "<api-name>api@project-id.iam.gserviceaccount.com",
                "client_id": "...",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://accounts.google.com/o/oauth2/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": "https://www.googleapis.com/...<api-name>api%40project-id.iam.gserviceaccount.com"
            }
    """
    key = {}
    service_account = get_google_service_account_for_client(client_id, user_id)

    if not service_account:
        if client_id:
            service_account = _create_google_service_account_for_client(
                client_id, user_id, proxy_group_id)
        else:
            # error about requiring client id in azp field of token
            flask.abort(
                404, 'Could not find client id in `azp` field of token. '
                'Cannot create Google key.')

    with GoogleCloudManager() as g_cloud:
        key = g_cloud.get_access_key(service_account.google_unique_id)

    return key, service_account


def get_linked_google_account_email(user_id):
    email = None
    user_google_account = (
        current_session.query(UserGoogleAccount)
        .filter(UserGoogleAccount.user_id == user_id).first()
    )
    if user_google_account:
        email = user_google_account.email
    return email


def add_custom_service_account_key_expiration(
        key_id, service_account_id, expires):
    """
    Add db entry of user service account key and its custom expiration.
    """
    sa_key = GoogleServiceAccountKey(
        key_id=key_id,
        service_account_id=service_account_id,
        expires=expires
    )
    current_session.add(sa_key)
    current_session.commit()


def get_google_service_account_for_client(client_id, user_id):
    """
    Return the service account (from Fence db) for given client.

    Get the service account that is associated with the given client
    for this user. There will be a single service account per client.

    NOTE: The user themselves have a "primary" service account which you
          can retrieve by passing in `None` as the client_id.

    Returns:
        fence.models.GoogleServiceAccount: Client's service account
    """
    service_account = (
        current_session
        .query(GoogleServiceAccount)
        .filter_by(client_id=client_id,
                   user_id=user_id)
        .first()
    )

    return service_account


def _create_users_primary_google_service_account_key(
        user_id, proxy_group_id, expires=None):
    expires = expires or (
        int(time.time())
        + flask.current_app.config['GOOGLE_SERVICE_ACCOUNT_KEY_FOR_URL_SIGNING_EXPIRES_IN']
    )
    sa_private_key, service_account = create_google_access_key_for_client(
        None, user_id, proxy_group_id)

    key_id = sa_private_key.get('private_key_id')
    sa_key = GoogleServiceAccountKey(
        key_id=key_id,
        service_account_id=service_account.id,
        expires=expires,
        private_key=sa_private_key
    )
    current_session.add(sa_key)
    current_session.commit()

    return sa_private_key


def _create_google_service_account_for_client(
        client_id, user_id, proxy_group_id):
    """
    Create a Google Service account for the current client and user.

    Args:
        g_cloud_manager (cirrus.GoogleCloudManager): instance of
        cloud manager to use

    Returns:
        fence.models.GoogleServiceAccount: New service account
    """
    if proxy_group_id:
        service_account_id = get_valid_service_account_id_for_client(
            client_id, user_id)

        with GoogleCloudManager() as g_cloud:
            new_service_account = (
                g_cloud.create_service_account_for_proxy_group(
                    proxy_group_id, account_id=service_account_id)
            )

        service_account = GoogleServiceAccount(
            google_unique_id=new_service_account['uniqueId'],
            client_id=client_id,
            user_id=user_id,
            email=new_service_account['email']
        )

        current_session.add(service_account)
        current_session.commit()

        return service_account
    else:
        flask.abort(
            404, 'Could not find Google proxy group for current user in the '
            'given token.')
