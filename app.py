import logging
import os

from tda import auth
from tda.orders.options import OptionSymbol
import datetime
from chalice import Chalice
import shutil


app = Chalice(app_name='tradingApp')
app.log.setLevel(logging.DEBUG)

f = open('chalicelib/apiKey', 'r')
api_key = f.readline()
f.close()

f = open('chalicelib/passphrase', 'r')
password = f.readline()
f.close()

acct_id = 237441143
symbol = "SPY"

global longPos
global longQty

global shortPos
global shortQty

# Note that the default token path is read-only
default_token_path = os.path.join(os.path.dirname(__file__), 'chalicelib', 'token')

# This path is not read-only on Lambda
aws_token_path = "/tmp/token"

redirect_uri = 'https://c06hbviu57.execute-api.us-west-2.amazonaws.com/api/'

try:
    # Try to authenticate to tda
    c = auth.client_from_token_file(aws_token_path, api_key)
except:
    try :
        # Move token file from chalice lib to EFS
        shutil.copyfile(default_token_path, aws_token_path)
        c = auth.client_from_token_file(aws_token_path, api_key)
    except:
        app.log.error("Unable to authenticate with tda, check that token file is not broken")

    # Use this code commented out locally to get a new token file
    #app.log.warning("Token file not found, trying to find from driver. Can not run this on AWS Lambda")
    #driver = webdriver.Chrome(executable_path="C:/Users/chimpKing/Downloads/chromedriver_win32/chromedriver.exe")
    #c = auth.client_from_login_flow(driver, api_key, redirect_uri, aws_token_path)


def option_chain(symbol, price, date, rangeDate):
    response = c.get_option_chain(symbol, from_date = rangeDate, to_date = rangeDate, strike_count=5)

    out = list(response.json()['callExpDateMap'])
    for i in out:
        if date in i:
            break

    assert isinstance(i, object)

    callPrice = response.json()['callExpDateMap'][i][price][0]['mark']
    putPrice = response.json()['putExpDateMap'][i][price][0]['mark']
    return i[:-2], callPrice, putPrice


@app.route('/account/balance', methods=['GET'])
def getAccountBalance():
    return c.get_accounts().json()[0]['securitiesAccount']['currentBalances']['liquidationValue']


@app.route('/account/positions', methods=['GET'])
def getPositions():
    orderDate = datetime.datetime.today()

    todaysFilledOrdersJson = c.get_orders_by_query(from_entered_datetime=orderDate, status=c.Order.Status.FILLED).json()

    symbolOne = todaysFilledOrdersJson[0]['orderLegCollection'][0]['instrument']['symbol']
    quantityOne = todaysFilledOrdersJson[0]['orderLegCollection'][0]['quantity']

    symbolTwo = todaysFilledOrdersJson[1]['orderLegCollection'][0]['instrument']['symbol']
    quantityTwo = todaysFilledOrdersJson[1]['orderLegCollection'][0]['quantity']

    return symbolOne, quantityOne, symbolTwo, quantityTwo


@app.route('/account/dayTrades', methods=['GET'])
def isOverDayTrades():
    isTooManyDayTrades = int(c.get_accounts().json()[0]['securitiesAccount']['roundTrips']) > 1
    return isTooManyDayTrades


def balance():
    response = c.get_accounts()

    # return current buying power and number of day trades
    return response.json()[0]['securitiesAccount']['currentBalances']['buyingPowerNonMarginableTrade'], int(response.json()[0]['securitiesAccount']['roundTrips'])


def getNextFriday(today):
    friday = today + datetime.timedelta((3 - today.weekday()) % 7 + 1)
    return friday.strftime("%Y-%m-%d"), friday


def place_buyOrder():
    global longQty
    global shortQty
    global longPos
    global shortPos
    global acct_id

    callOrder = {
        "complexOrderStrategyType": "NONE",
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "BUY_TO_OPEN",
                "quantity": longQty,
                "instrument": {
                    "symbol": longPos,
                    "assetType": "OPTION"
                }
            }
        ]
    }

    putOrder = {
        "complexOrderStrategyType": "NONE",
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "BUY_TO_OPEN",
                "quantity": shortQty,
                "instrument": {
                    "symbol": shortPos,
                    "assetType": "OPTION"
                }
            }
        ]
    }

    c.place_order(acct_id, callOrder)
    c.place_order(acct_id, putOrder)

    print("Placed order with the following: ")
    print("Long: " + longPos + " Qty: " + str(longQty))
    print("Short: " + shortPos + " Qty: " + str(shortQty))

    return {
        "code": "Order Succeeded"
    }


def place_sellOrder():
    global longQty
    global shortQty
    global longPos
    global shortPos
    global acct_id

    longPos, longQty, shortPos, shortQty = getPositions()

    putClose = {
        "complexOrderStrategyType": "NONE",
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "SELL_TO_CLOSE",
                "quantity": longPos,
                "instrument": {
                    "symbol": longQty,
                    "assetType": "OPTION"
                }
            }
        ]
    }

    callClose = {
        "complexOrderStrategyType": "NONE",
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "SELL_TO_CLOSE",
                "quantity": shortPos,
                "instrument": {
                    "symbol": shortQty,
                    "assetType": "OPTION"
                }
            }
        ]
    }

    c.place_order(acct_id, putClose)
    c.place_order(acct_id, callClose)

    print("Closed order with the following: ")
    print("Long: " + longPos + " Qty: " + str(longQty))
    print("Short: " + shortPos + " Qty: " + str(shortQty))

    return {
        "code": "Sell order Succeeded"
    }


@app.route('/option/order', methods=['POST'])
def option_order():
    global symbol
    global longQty
    global shortQty
    global longPos
    global shortPos

    webhook_message = app.current_request.json_body
    print(webhook_message)

    if "Long" in webhook_message['direction']:

        if webhook_message['passphrase'] != password:
            app.log.error("wrong password")
            return {
                "code": "error",
                "message": "Wrong password long position"
            }
 
        if "buy" in webhook_message['action']:
            # Get next Friday after today's date
            nextFriday, rangeFriday = getNextFriday(datetime.date.today())

            # Get current price of SPY at close
            price = webhook_message['price']
            price = str(float(int(price) + 1))

            # Get option data and price
            buyDate, callPrice, putPrice = option_chain(symbol, price, nextFriday, rangeFriday)
            buyDate = datetime.datetime.strptime(buyDate, '%Y-%m-%d')
            buyDate = buyDate.strftime("%m%d%y")

            # Build option symbol for the long and short positions
            longPos = OptionSymbol(symbol, buyDate, 'C', price).build()
            shortPos = OptionSymbol(symbol, buyDate, 'P', price).build()

            print("Call price is " + str(callPrice))

            # Get quantities from current account balance
            acctBal, dayTrades = balance()
            acctBal = int(acctBal)
            dayTrades = int(dayTrades)

            # Check if we have enough day trades and that account balance is under $25,000
            if dayTrades > 1 & acctBal < 25000:
                app.log.error("Error, too many day trades")
                return

            longQty = int((acctBal * .7) / (100 * callPrice))
            shortQty = int((acctBal * .3) / (100 * putPrice))

            # Place the order
            place_buyOrder()

        if "sell" in webhook_message['action']:
            place_sellOrder()

    if "Short" in webhook_message['direction']:
        # Check that the password is correct
        if webhook_message['passphrase'] != password:
            app.log.error("wrong password")
            return {
                "code": "error",
                "message": "Wrong password long position"
            }

        if "sell" in webhook_message['action']:
            # Get next Friday after today's date
            nextFriday, rangeFriday = getNextFriday(datetime.date.today())

            # Get current price of SPY at close
            price = webhook_message['price']
            price = str(float(int(price) - 1))

            # Get option data and price
            buyDate, callPrice, putPrice = option_chain(symbol, price, nextFriday, rangeFriday)
            buyDate = datetime.datetime.strptime(buyDate, '%Y-%m-%d')
            buyDate = buyDate.strftime("%m%d%y")

            # Build option symbol for the long and short positions
            longPos = OptionSymbol(symbol, buyDate, 'C', price).build()
            shortPos = OptionSymbol(symbol, buyDate, 'P', price).build()

            # Get quantities from current account balance and number of day trades
            acctBal, dayTrades = balance()
            acctBal = int(acctBal)
            dayTrades = int(dayTrades)

            # Don't place an order if there are more than 3 day trades already
            if dayTrades > 1 & acctBal < 25000:
                app.log.error("Error, too many day trades")
                return


            longQty = int((acctBal * .3) / (100 * callPrice))
            shortQty = int((acctBal * .7) / (100 * putPrice))

            # Place the order
            place_buyOrder()

        if "buy" in webhook_message['action']:
            place_sellOrder()
