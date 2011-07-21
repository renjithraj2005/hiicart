import urllib
import httplib2
from cgi import parse_qs

from django.utils.safestring import mark_safe
from django.utils.datastructures import SortedDict

from hiicart.gateway.base import PaymentGatewayBase
from hiicart.gateway.paypal_express_checkout.settings import SETTINGS as default_settings

NVP_SIGNATURE_TEST_URL = "https://api-3t.sandbox.paypal.com/nvp"
NVP_SIGNATURE_URL = "https://api-3t.paypal.com/nvp"
REDIRECT_URL = "https://www.paypal.com/cgi-bin/webscr?cmd=_express-checkout&token=%s"
REDIRECT_TEST_URL = "https://www.sandbox.paypal.com/cgi-bin/webscr?cmd=_express-checkout&token=%s"

NO_SHIPPING = {
    "REQUIRE": "2",
    "NO" : "1",
    "YES" : "0"
    }
ALLOW_NOTE = {
    "YES" : "1",
    "NO" : "0"
    }
RECURRING_PAYMENT = {
    "YES" : "1",
    "NO" : "0"
    }

class PaypalExpressCheckoutGateway(PaymentGatewayBase):
    """Paypal Express Checkout processor"""

    def __init__(self, cart):
        def __init__(self, cart):
            super(PaypalExpressCheckoutGateway, self).__init__('paypal_express', cart, default_settings)
            self._require_settings(['API_USERNAME', 'API_PASSWORD', 'API_SIGNATURE'])

        @property
        def _nvp_url(self):
            """URL to post NVP API call to"""
            if self.settings['LIVE']:
                url = NVP_SIGNATURE_URL
            else:
                url = NVP_SIGNATURE_TEST_URL
            return mark_safe(url)

        def _do_nvp(self, method, params_dict):
            http = httplib2.Http()
            params_dict['method'] = method
            params_dict['user'] = self.settings['API_USERNAME']
            params_dict['pwd'] = self.settings['API_PASSWORD']
            params_dict['signature'] = self.settings['API_SIGNATURE']
            params_dict['version'] = self.settings['API_VERSION']
            encoded_params = urllib.urlencode(params_dict)

            response, content = http.request(self._nvp_url, 'POST', encoded_params)
            response_dict = parse_qs(content)
            if response_dict['ACK'] != 'Success':
                raise GatewayError("Error calling Paypal %s" % method)
            return response_dict

        def _create_redirect_url(self, token):
            """Construct user redirect url from token"""
            if self.settings['LIVE']:
                base = REDIRECT_URL
            else:
                base = REDIRECT_TEST_URL
            return base % token
        
        def _get_checkout_data(self):
            """Populate request params from shopping cart"""
            params = SortedDict()

            # Urls for returning user after leaving Paypal
            if self.settings.get('SHOPPING_URL'):
                params['returnurl'] = self.settings['SHOPPING_URL']
            if self.settings.get('CANCEL_RETURN'):
                params['cancelurl'] = self.settings['CANCEL_RETURN']

            params['localecode'] = self.settings['LOCALE']

            if self.settings.get('NO_SHIPPING'):
                params['noshipping'] = self.settings['NO_SHIPPING']
            else:
                params['noshipping'] = NO_SHIPPING['YES']

            params['allownote'] = '1'

            # We don't support parallel payments, so all PAYMENTREQUEST fields will
            # just use this one prefix
            pre = 'paymentrequest_0_'
            
            params[pre+'invnum'] = self.cart.cart_uuid
            params[pre+'currencycode'] = self.settings['CURRENCY_CODE']
            # Total cost of transaction to customer, including shipping, handling, and tax if known
            params[pre+'amt'] = self.cart.total
            # Sub-total of all items in order
            params[pre+'itemamt'] = self.cart.sub_total
            # Shipping amount
            params[pre+'shippingamt'] = self.cart.shipping
            # Tax amount
            params[pre+'taxamt'] = self.cart.tax
            # Not using parallel payments, so this is always Sale
            params[pre+'paymentaction'] = 'Sale'

            pre = 'l_paymentrequest_0_'

            if len(self.cart.recurrint_lineitems) > 0:
                # TODO
                pass
                params['l_billingtype%i' % idx] = 'RecurringPayments'
            else:
                idx = 0
                for item in self.cart.one_time_lineitems:
                    params[pre+'name%i' % idx] = item.name
                    params[pre+'desc%i' % idx] = item.description
                    params[pre+'amt%i' % idx] = item.total
                    params[pre+'qty%i' % idx] = item.quantity
                    params[pre+'number%i' % idx] = item.sku
                    idx += 1

            if self.cart.bill_street1:
                params['addroverride'] = '0'
                params['email'] = self.cart.bill_email
                params[pre+'shiptoname'] = '%s %s' % (self.cart.bill_first_name, self.car.bill_last_name)
                params[pre+'shiptostreet'] = self.cart.bill_street1
                params[pre+'shiptostreet2'] = self.cart.bill_street2
                params[pre+'shiptocity'] = self.cart.bill_city
                params[pre+'shiptostate'] = self.cart.bill_state
                params[pre+'shiptocountrycode'] = self.cart.bill_country
                params[pre+'shiptozip'] = self.cart.bill_zip

            return params
                

        def submit(self, collect_address=False, cart_settings_kwargs=None, modify_existing_cart=False):
            """Submit order details to the gateway.

            * Server POSTs an API call to Paypal
            * Paypal returns a response that includes an URL to redirect the user to"""
            self._update_with_cart_settings(cart_settings_kwargs)

            params = self._get_checkout_data()
            response = self._do_nvp('SetExpressCheckout', params)
            
            url = self._create_redirect_url(response['TOKEN'])
            return SubmitResult('url', url)

        def get_details(self, token):
            """Get details from Paypal about payer and payment."""
            params = {'token' : token}
            response = self._do_nvp('GetExpressCheckoutDetails', params)
            return response

        def confirm(self, token, payerid):
            params = self._get_checkout_data()
            params['token'] = token
            params['payerid'] = payerid

            response = self._do_nvp('DoExpressCheckoutPayment', params)

