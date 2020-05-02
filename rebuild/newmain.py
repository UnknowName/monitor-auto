from abc import ABCMeta, abstractmethod


class WaterHeater(object):
    def __init__(self):
        self.__observers = []
        self.__temperature = 25

    def get_temperature(self):
        return self.__temperature

    def set_temperature(self, temperature: int):
        self.__temperature = temperature
        self.notifies()

    def add_observer(self, observer):
        self.__observers.append(observer)

    def notifies(self):
        for obj in self.__observers:
            obj.update(self)


class Observer(metaclass=ABCMeta):

    @abstractmethod
    def update(self, wh: WaterHeater):
        pass


class WashMode(Observer):
    def update(self, wh: WaterHeater):
        curr_temperature = wh.get_temperature()
        if 25 < curr_temperature < 75:
            print("Can washing now!")


class DrinkMode(Observer):
    def update(self, wh: WaterHeater):
        curr_temperature = wh.get_temperature()
        if curr_temperature >= 100:
            print("Can drink")


if __name__ == '__main__':
    water = WaterHeater()
    wash_obser = WashMode()
    drink_obser = DrinkMode()
    water.add_observer(wash_obser)
    water.add_observer(drink_obser)
    water.set_temperature(10)
    water.set_temperature(70)
    water.set_temperature(100)


