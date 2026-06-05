import { NestFactory } from '@nestjs/core'
import { ValidationPipe } from '@nestjs/common'
import { AppModule } from './app.module'
import helmet from 'helmet'

async function bootstrap() {
  const app = await NestFactory.create(AppModule)

  app.use(helmet())
  app.setGlobalPrefix('api/v1')
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, transform: true }))

  app.enableCors({
    origin: process.env.FRONTEND_URL,
    methods: ['GET', 'POST', 'PATCH', 'DELETE'],
    credentials: true,
  })

  await app.listen(process.env.PORT || 3000)
  console.log(`🚀 REESTOR Backend running on port ${process.env.PORT || 3000}`)
}

bootstrap()
